"""DOC/DOCX -> TXT conversion.

- ``.docx`` is parsed in-process with ``python-docx``.
- legacy ``.doc`` is converted with a headless LibreOffice subprocess that has
  a hard timeout and never uses a shell.

No other conversion formats are supported.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from bot.config import Settings
from bot.services.filetypes import ext_of

ProgressFn = Callable[[int], None]


class ConversionError(RuntimeError):
    """Raised when a document cannot be converted."""


def _docx_to_txt(src: Path, out: Path, on_progress: ProgressFn | None = None) -> int:
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise ConversionError("python-docx is not installed") from exc

    try:
        document = Document(str(src))
    except Exception as exc:  # noqa: BLE001 - python-docx raises many types
        raise ConversionError(f"Could not read DOCX: {exc}") from exc

    out.parent.mkdir(parents=True, exist_ok=True)
    paragraphs = 0
    with open(out, "w", encoding="utf-8", newline="\n") as handle:
        for paragraph in document.paragraphs:
            text = paragraph.text.replace("\r\n", "\n").replace("\r", "\n")
            handle.write(text + "\n")
            paragraphs += 1
            if on_progress:
                on_progress(paragraphs)
        for table in document.tables:
            handle.write("\n")
            for row in table.rows:
                handle.write("\t".join(cell.text for cell in row.cells) + "\n")
    return paragraphs


def _doc_to_txt(
    src: Path, out: Path, *, settings: Settings, on_progress: ProgressFn | None = None
) -> int:
    """Convert legacy ``.doc`` using headless LibreOffice."""
    with tempfile.TemporaryDirectory(prefix="doc2txt_") as tmp:
        outdir = Path(tmp)
        command = [
            settings.libreoffice_path,
            "--headless",
            "--norestore",
            "--convert-to",
            "txt:Text (encoded):UTF8",
            "--outdir",
            str(outdir),
            str(src),
        ]
        try:
            completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
                command,
                capture_output=True,
                timeout=settings.libreoffice_timeout_seconds,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ConversionError(
                f"LibreOffice timed out after {settings.libreoffice_timeout_seconds}s"
            ) from exc
        except FileNotFoundError as exc:
            raise ConversionError(
                f"LibreOffice executable not found: {settings.libreoffice_path!r}"
            ) from exc

        produced = outdir / f"{src.stem}.txt"
        if not produced.exists():
            candidates = sorted(outdir.glob("*.txt"))
            if not candidates:
                stderr = (completed.stderr or b"").decode("utf-8", "replace")[:300]
                raise ConversionError(f"LibreOffice produced no output. {stderr}".strip())
            produced = candidates[0]

        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(produced, out)

    if on_progress:
        on_progress(1)
    return 1


def convert_document(
    src: str | Path,
    out: str | Path,
    *,
    settings: Settings,
    on_progress: ProgressFn | None = None,
) -> int:
    """Convert ``.doc``/``.docx`` to UTF-8 text. Returns paragraph/line count."""
    source = Path(src)
    destination = Path(out)
    extension = ext_of(source.name)

    if extension == ".docx":
        return _docx_to_txt(source, destination, on_progress)
    if extension == ".doc":
        return _doc_to_txt(source, destination, settings=settings, on_progress=on_progress)
    raise ConversionError(f"Unsupported document format: {extension or '(none)'}")
