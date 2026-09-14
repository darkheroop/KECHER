"""Concrete job handlers for every file feature.

Handlers only produce files and return :class:`JobOutput`s; the
:class:`~bot.jobs.manager.JobManager` persists and delivers them.
"""

from __future__ import annotations

import asyncio
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from bot.config import Settings
from bot.db.engine import session_scope
from bot.db.enums import JobKind
from bot.db.repositories import (
    clear_queue,
    get_user_files_by_ids,
    list_queue_items,
)
from bot.jobs.context import JobContext, JobOutput, JobResult
from bot.jobs.execution import run_with_progress
from bot.jobs.manager import JobManager
from bot.services.csv_tool import csv_to_txt, inspect_csv
from bot.services.dataset import (
    count_records,
    export_group,
    inspect_dataset,
    search_to_file,
)
from bot.services.doc_convert import convert_document
from bot.services.scraper import ScrapeOptions
from bot.services.telegram_export import extract_to_txt
from bot.services.validation import ValidationOptions, validate_file
from bot.ui.emoji import Emoji
from bot.services.filetypes import as_txt_name
from bot.services.text_ops import (
    CleanOptions,
    clean_file,
    dedup_file,
    merge_files,
    split_file,
)


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _require_input(ctx: JobContext) -> Path:
    if ctx.input_path is None or not ctx.input_path.is_file():
        raise RuntimeError("Input file is missing")
    return ctx.input_path


def _out(ctx: JobContext, name: str):
    return ctx.files.allocate(ctx.telegram_id, name, subdir="out")


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #
async def _handle_doc2txt(ctx: JobContext, settings: Settings) -> JobResult:
    ctx.raise_if_cancelled()
    source = _require_input(ctx)
    target = _out(ctx, as_txt_name(source.name))

    paragraphs = await run_with_progress(
        convert_document,
        source,
        target.path,
        reporter=ctx.progress,
        total=max(1, _size(source)),
        label="Converting document",
        settings=settings,
    )
    ctx.raise_if_cancelled()
    stored = ctx.files.finalize(target)
    return JobResult(
        message=(
            "<b>Conversion complete</b>\n\n"
            f"Input: {source.name}\n"
            f"Output: {stored.safe_name}\n"
            f"Paragraphs: {paragraphs:,}"
        ),
        outputs=[JobOutput(stored, caption=f"Converted from {source.name}")],
        stats={"paragraphs": paragraphs},
    )


async def _handle_csv(ctx: JobContext, settings: Settings) -> JobResult:
    ctx.raise_if_cancelled()
    source = _require_input(ctx)
    info = await asyncio.to_thread(inspect_csv, source)
    ctx.raise_if_cancelled()

    columns = ctx.params.get("columns")
    target = _out(ctx, as_txt_name(source.name))
    written = await run_with_progress(
        csv_to_txt,
        source,
        target.path,
        reporter=ctx.progress,
        total=max(1, info.rows),
        label="Converting CSV",
        columns=columns,
    )
    ctx.raise_if_cancelled()
    stored = ctx.files.finalize(target)

    column_note = "all columns" if columns is None else f"{len(columns)} column(s)"
    return JobResult(
        message=(
            "<b>CSV converted</b>\n\n"
            f"Rows: {info.rows:,}\n"
            f"Columns: {info.columns}\n"
            f"Output columns: {column_note}\n"
            f"Lines written: {written:,}"
        ),
        outputs=[JobOutput(stored, caption=f"CSV to TXT ({column_note})")],
        stats={"rows": info.rows, "columns": info.columns, "written": written},
    )


async def _handle_split(ctx: JobContext, settings: Settings) -> JobResult:
    ctx.raise_if_cancelled()
    source = _require_input(ctx)
    mode = str(ctx.params.get("mode", "lines"))
    value = int(ctx.params.get("value", 1000))

    work_dir = ctx.workspace / "tmp" / f"split_{ctx.job_id}"
    result = await run_with_progress(
        split_file,
        source,
        work_dir,
        reporter=ctx.progress,
        total=max(1, _size(source)),
        label="Splitting",
        mode=mode,
        value=value,
    )
    ctx.raise_if_cancelled()

    if not result.files:
        raise RuntimeError("Nothing to split")

    if len(result.files) == 1:
        target = _out(ctx, result.files[0].name)
        shutil.move(str(result.files[0]), str(target.path))
    else:
        target = _out(ctx, f"{source.stem}_split.zip")
        with zipfile.ZipFile(target.path, "w", zipfile.ZIP_DEFLATED) as archive:
            for part in result.files:
                archive.write(part, arcname=part.name)
        shutil.rmtree(work_dir, ignore_errors=True)

    stored = ctx.files.finalize(target)
    return JobResult(
        message=(
            "<b>Split complete</b>\n\n"
            f"Parts: {len(result.files):,}\n"
            f"Lines: {result.lines:,}\n"
            f"Mode: {mode} = {value}"
        ),
        outputs=[JobOutput(stored, caption=f"Split into {len(result.files)} file(s)")],
        stats={"parts": len(result.files), "lines": result.lines},
    )


async def _handle_clean(ctx: JobContext, settings: Settings) -> JobResult:
    ctx.raise_if_cancelled()
    source = _require_input(ctx)
    raw = ctx.params.get("options") or {}
    options = CleanOptions(
        remove_empty=bool(raw.get("remove_empty", True)),
        trim=bool(raw.get("trim", True)),
        separator=raw.get("separator") or None,
        remove_malformed=bool(raw.get("remove_malformed", False)),
        min_fields=int(raw.get("min_fields", 1)),
        sort=bool(raw.get("sort", False)),
        dedup=bool(raw.get("dedup", False)),
        normalize_dupes=bool(raw.get("normalize_dupes", False)),
        luhn=bool(raw.get("luhn", False)),
        luhn_field=raw.get("luhn_field"),
    )
    target = _out(ctx, f"cleaned_{source.name}")
    result = await run_with_progress(
        clean_file,
        source,
        target.path,
        options,
        reporter=ctx.progress,
        total=max(1, _size(source)),
        label="Cleaning",
    )
    ctx.raise_if_cancelled()
    stored = ctx.files.finalize(target)

    lines = [
        "<b>Cleaning complete</b>",
        "",
        f"Total: {result.total:,}",
        f"Passed: {result.passed:,}",
        f"Rejected: {result.rejected:,}",
        f"Duplicates: {result.duplicates:,}",
        f"Empty removed: {result.empty:,}",
    ]
    if options.luhn or options.luhn_field is not None:
        lines.extend(
            [
                "",
                f"Luhn checked: {result.luhn_checked:,}",
                f"Luhn valid: {result.luhn_valid:,}",
                f"Luhn invalid: {result.luhn_invalid:,}",
                "",
                "This was a local mathematical test only.",
                "No external payment service was contacted.",
            ]
        )
    return JobResult(
        message="\n".join(lines),
        outputs=[JobOutput(stored, caption="Cleaned dataset")],
        stats={
            "total": result.total,
            "passed": result.passed,
            "rejected": result.rejected,
            "duplicates": result.duplicates,
            "empty": result.empty,
            "luhn_checked": result.luhn_checked,
            "luhn_valid": result.luhn_valid,
            "luhn_invalid": result.luhn_invalid,
        },
    )


async def _handle_dedup(ctx: JobContext, settings: Settings) -> JobResult:
    ctx.raise_if_cancelled()
    source = _require_input(ctx)
    normalize = bool(ctx.params.get("normalize", False))
    target = _out(ctx, f"dedup_{source.name}")
    result = await run_with_progress(
        dedup_file,
        source,
        target.path,
        reporter=ctx.progress,
        total=max(1, _size(source)),
        label="Deduplicating",
        normalize=normalize,
    )
    ctx.raise_if_cancelled()
    stored = ctx.files.finalize(target)
    return JobResult(
        message=(
            "<b>Deduplication complete</b>\n\n"
            f"Original: {result.original:,}\n"
            f"Unique: {result.unique:,}\n"
            f"Removed: {result.removed:,}"
        ),
        outputs=[JobOutput(stored, caption="Deduplicated dataset")],
        stats={
            "original": result.original,
            "unique": result.unique,
            "removed": result.removed,
        },
    )


async def _handle_merge(ctx: JobContext, settings: Settings) -> JobResult:
    ctx.raise_if_cancelled()
    async with session_scope() as session:
        items = await list_queue_items(session, ctx.user_id)
        records = await get_user_files_by_ids(
            session, ctx.user_id, [item.file_id for item in items]
        )
        rel_paths = [record.rel_path for record in records]

    if not rel_paths:
        raise RuntimeError("Merge queue is empty")

    paths = [ctx.files.resolve(ctx.telegram_id, rel) for rel in rel_paths]
    total = sum(_size(path) for path in paths)

    dedup = bool(ctx.params.get("dedup", False))
    sort = bool(ctx.params.get("sort", False))
    target = _out(ctx, "merged.txt")

    result = await run_with_progress(
        merge_files,
        paths,
        target.path,
        reporter=ctx.progress,
        total=max(1, total),
        label="Merging",
        dedup=dedup,
        normalize=dedup,
        sort=sort,
    )
    ctx.raise_if_cancelled()

    async with session_scope() as session:
        await clear_queue(session, ctx.user_id)

    stored = ctx.files.finalize(target)
    options = ", ".join(
        filter(None, ["dedup" if dedup else "", "sort" if sort else ""])
    )
    return JobResult(
        message=(
            "<b>Merge complete</b>\n\n"
            f"Files merged: {result.files:,}\n"
            f"Total lines: {result.total:,}\n"
            f"Lines written: {result.written:,}\n"
            f"Duplicates removed: {result.duplicates:,}\n"
            f"Options: {options or 'none'}"
        ),
        outputs=[JobOutput(stored, caption="Merged dataset")],
        stats={
            "files": result.files,
            "total": result.total,
            "written": result.written,
            "duplicates": result.duplicates,
        },
    )


# --------------------------------------------------------------------------- #
# Data-tool handlers
# --------------------------------------------------------------------------- #
def _slug(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in value).strip("_")
    return (cleaned or "group")[:60]


async def _handle_find(ctx: JobContext, settings: Settings) -> JobResult:
    ctx.raise_if_cancelled()
    source = _require_input(ctx)
    info = await asyncio.to_thread(inspect_dataset, source)
    total = await asyncio.to_thread(count_records, source, info)

    query = str(ctx.params.get("query", ""))
    mode = str(ctx.params.get("mode", "contains"))
    field_index = ctx.params.get("field")
    case_sensitive = bool(ctx.params.get("case_sensitive", False))

    target = _out(ctx, f"found_{source.stem}.txt")
    result = await run_with_progress(
        search_to_file,
        source,
        target.path,
        reporter=ctx.progress,
        total=max(1, total),
        label="Searching",
        info=info,
        query=query,
        mode=mode,
        field_index=field_index,
        case_sensitive=case_sensitive,
    )
    ctx.raise_if_cancelled()
    stored = ctx.files.finalize(target)

    samples = "\n".join(f"• <code>{sample}</code>" for sample in result.samples)
    message = (
        "<b>Search complete</b>\n\n"
        f"Mode: {mode}\n"
        f"Scanned: {result.scanned:,}\n"
        f"Matches: {result.matches:,}"
    )
    if samples:
        message += f"\n\n<b>Samples (masked)</b>\n{samples}"

    return JobResult(
        message=message,
        outputs=[JobOutput(stored, caption=f"{result.matches} match(es) for '{query}'")]
        if result.matches
        else [],
        stats={"scanned": result.scanned, "matches": result.matches},
    )


async def _handle_pick(ctx: JobContext, settings: Settings) -> JobResult:
    ctx.raise_if_cancelled()
    source = _require_input(ctx)
    info = await asyncio.to_thread(inspect_dataset, source)
    total = await asyncio.to_thread(count_records, source, info)

    field_index = ctx.params.get("field")
    value = str(ctx.params.get("value", ""))
    case_sensitive = bool(ctx.params.get("case_sensitive", False))

    target = _out(ctx, f"pick_{_slug(value)}.txt")
    written = await run_with_progress(
        export_group,
        source,
        target.path,
        reporter=ctx.progress,
        total=max(1, total),
        label="Exporting group",
        info=info,
        field_index=field_index,
        value=value,
        case_sensitive=case_sensitive,
    )
    ctx.raise_if_cancelled()
    if written == 0:
        target.path.unlink(missing_ok=True)
        return JobResult(message=f"No records found for '{value}'.", outputs=[])

    stored = ctx.files.finalize(target)
    return JobResult(
        message=f"<b>Group exported</b>\n\nValue: {value}\nRecords: {written:,}",
        outputs=[JobOutput(stored, caption=f"{value} ({written:,} records)")],
        stats={"value": value, "written": written},
    )


async def _handle_pickbank(ctx: JobContext, settings: Settings) -> JobResult:
    return await _handle_pick(ctx, settings)


# --------------------------------------------------------------------------- #
# Authorized-source scraping
# --------------------------------------------------------------------------- #
def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


async def _handle_scrape(ctx: JobContext, scraper) -> JobResult:  # noqa: ANN001
    ctx.raise_if_cancelled()
    if scraper is None or not getattr(scraper, "available", lambda: False)():
        raise RuntimeError(
            "No Telegram account is configured. Run `python -m bot.tools.plogin` "
            "locally and set TELEGRAM_API_ID / TELEGRAM_API_HASH."
        )

    params = ctx.params
    fmt = str(params.get("format", "txt"))
    options = ScrapeOptions(
        limit=max(1, int(params.get("limit", 100))),
        date_from=_parse_dt(params.get("date_from")),
        date_to=_parse_dt(params.get("date_to")),
        keyword=params.get("keyword") or None,
        types=set(params["types"]) if params.get("types") else None,
        include_media=bool(params.get("include_media", False)),
    )
    label = str(params.get("account", ""))
    peer = str(params.get("peer", ""))

    extension = {"txt": "txt", "csv": "csv", "json": "json"}.get(fmt, "txt")
    target = _out(ctx, f"scrape_{_slug(peer)}.{extension}")

    await ctx.progress.update(5, label="Collecting messages", force=True)
    result = await scraper.scrape(
        label=label,
        peer_ref=peer,
        out=target.path,
        options=options,
        fmt=fmt,
    )
    ctx.raise_if_cancelled()
    stored = ctx.files.finalize(target)

    message = (
        "<b>Scrape complete</b>\n\n"
        f"Source: {peer}\n"
        f"Scanned: {result.scanned:,}\n"
        f"Exported: {result.exported:,}\n"
        f"Format: {fmt.upper()}"
    )
    outputs = (
        [JobOutput(stored, caption=f"{result.exported:,} message(s) from {peer}")]
        if result.exported
        else []
    )
    if not result.exported:
        target.path.unlink(missing_ok=True)
    return JobResult(
        message=message,
        outputs=outputs,
        stats={"scanned": result.scanned, "exported": result.exported, "format": fmt},
    )


# --------------------------------------------------------------------------- #
# Telegram export import
# --------------------------------------------------------------------------- #
async def _handle_extract(ctx: JobContext, settings: Settings) -> JobResult:
    ctx.raise_if_cancelled()
    source = _require_input(ctx)
    target = _out(ctx, as_txt_name(source.name))

    count = await run_with_progress(
        extract_to_txt,
        source,
        target.path,
        reporter=ctx.progress,
        total=max(1, _size(source)),
        label="Extracting messages",
    )
    ctx.raise_if_cancelled()

    if count == 0:
        target.path.unlink(missing_ok=True)
        return JobResult(message="No messages found in that export.", outputs=[])

    stored = ctx.files.finalize(target)
    return JobResult(
        message=(
            "<b>Extraction complete</b>\n\n"
            f"Messages: {count:,}\n"
            f"Output: {stored.safe_name}\n\n"
            "Next: send this TXT to /clean and enable "
            "<b>Luhn check all (offline)</b>."
        ),
        outputs=[JobOutput(stored, caption=f"{count:,} message(s) extracted")],
        stats={"messages": count},
    )


# --------------------------------------------------------------------------- #
# Offline test-data validation
# --------------------------------------------------------------------------- #
def _resolve_field_indices(info, params: dict) -> tuple[int | None, int | None]:
    from bot.services.dataset import detect_field

    pan_candidates = {"pan", "card", "card_number", "number", "cc", "cardnumber"}
    expiry_candidates = {"expiry", "exp", "exp_date", "expiry_date", "valid_thru", "expdate"}

    if info.kind == "csv" and info.header:
        pan_index = detect_field(info.header, pan_candidates)
        expiry_index = detect_field(info.header, expiry_candidates)
        if pan_index is None:
            pan_index = 0
        return pan_index, expiry_index

    pan_index = params.get("pan_index", 0)
    expiry_index = params.get("expiry_index", 1 if info.columns >= 2 else None)
    return pan_index, expiry_index


async def _handle_validate(ctx: JobContext, settings: Settings) -> JobResult:
    ctx.raise_if_cancelled()
    source = _require_input(ctx)
    info = await asyncio.to_thread(inspect_dataset, source)
    total = await asyncio.to_thread(count_records, source, info)
    pan_index, expiry_index = _resolve_field_indices(info, ctx.params)

    raw = ctx.params.get("options") or {}
    options = ValidationOptions(
        check_format=bool(raw.get("format", True)),
        check_length=bool(raw.get("length", True)),
        check_luhn=bool(raw.get("luhn", True)),
        check_test_bin=bool(raw.get("test_bin", False)),
        check_expiry=bool(raw.get("expiry", True)),
        flag_expired=bool(raw.get("flag_expired", True)),
    )

    target = _out(ctx, f"validation_{source.stem}.csv")
    report = await run_with_progress(
        validate_file,
        source,
        target.path,
        reporter=ctx.progress,
        total=max(1, total),
        label="Validating test data",
        info=info,
        pan_index=pan_index,
        expiry_index=expiry_index,
        options=options,
    )
    ctx.raise_if_cancelled()
    stored = ctx.files.finalize(target)

    networks = ", ".join(
        f"{name}: {count:,}" for name, count in report.networks.most_common(5)
    )
    lines = [
        f"{Emoji.SECURITY} <b>TEST MODE</b>",
        "",
        "Local validation only.",
        "No payment network was contacted.",
        "",
        f"Total: {report.total:,}",
        f"Valid: {report.valid:,}",
        f"Invalid: {report.invalid:,}",
        f"Luhn failures: {report.luhn_failures:,}",
        f"Length failures: {report.length_failures:,}",
        f"Expiry failures: {report.expiry_failures:,}",
        f"Duplicates: {report.duplicates:,}",
        f"Official test BINs: {report.test_bin_count:,}",
    ]
    if networks:
        lines.append(f"Networks: {networks}")
    if report.samples:
        lines.append("")
        lines.append("<b>Sample failures (masked)</b>")
        lines.extend(f"• <code>{sample}</code>" for sample in report.samples)
    lines.extend(["", "CVV/CVC is never collected or validated."])

    return JobResult(
        message="\n".join(lines),
        outputs=[JobOutput(stored, caption="Test-data validation report")],
        stats={
            "total": report.total,
            "valid": report.valid,
            "invalid": report.invalid,
            "luhn_failures": report.luhn_failures,
            "test_bin_count": report.test_bin_count,
        },
    )


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #
def register_handlers(manager: JobManager, settings: Settings, scraper=None) -> None:  # noqa: ANN001
    """Register all built-in job handlers on ``manager``."""

    async def doc2txt(ctx: JobContext) -> JobResult:
        return await _handle_doc2txt(ctx, settings)

    async def csv(ctx: JobContext) -> JobResult:
        return await _handle_csv(ctx, settings)

    async def split(ctx: JobContext) -> JobResult:
        return await _handle_split(ctx, settings)

    async def clean(ctx: JobContext) -> JobResult:
        return await _handle_clean(ctx, settings)

    async def dedup(ctx: JobContext) -> JobResult:
        return await _handle_dedup(ctx, settings)

    async def merge(ctx: JobContext) -> JobResult:
        return await _handle_merge(ctx, settings)

    async def find(ctx: JobContext) -> JobResult:
        return await _handle_find(ctx, settings)

    async def pick(ctx: JobContext) -> JobResult:
        return await _handle_pick(ctx, settings)

    async def pickbank(ctx: JobContext) -> JobResult:
        return await _handle_pickbank(ctx, settings)

    async def scrape(ctx: JobContext) -> JobResult:
        return await _handle_scrape(ctx, scraper)

    async def validate(ctx: JobContext) -> JobResult:
        return await _handle_validate(ctx, settings)

    async def extract(ctx: JobContext) -> JobResult:
        return await _handle_extract(ctx, settings)

    manager.register(JobKind.DOC2TXT, doc2txt)
    manager.register(JobKind.EXTRACT, extract)
    manager.register(JobKind.CSV, csv)
    manager.register(JobKind.SPLIT, split)
    manager.register(JobKind.CLEAN, clean)
    manager.register(JobKind.DEDUP, dedup)
    manager.register(JobKind.MERGE, merge)
    manager.register(JobKind.FIND, find)
    manager.register(JobKind.PICK, pick)
    manager.register(JobKind.PICKBANK, pickbank)
    manager.register(JobKind.SCRAPE, scrape)
    manager.register(JobKind.VALIDATE, validate)
