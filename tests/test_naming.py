"""Output filename rendering and the custom-name settings."""

from __future__ import annotations

from datetime import UTC, datetime

from bot.services import naming, prefs

MOMENT = datetime(2026, 9, 17, 20, 51, tzinfo=UTC)


def test_default_names_are_operation_based() -> None:
    assert naming.render(None, op="cleaned") == "cleaned.txt"
    assert naming.render(None, op="deduped") == "deduped.txt"
    assert naming.render(None, op="merged") == "merged.txt"


def test_index_is_appended_for_default_and_custom() -> None:
    assert naming.render(None, op="part", index=1) == "part-1.txt"
    assert naming.render(None, op="part", index=3) == "part-3.txt"
    assert naming.render("mycards_{op}", op="part", index=2) == "mycards_part-2.txt"
    assert naming.render("mycards_{op}_{index}", op="part", index=2) == "mycards_part_2.txt"


def test_placeholders_expand() -> None:
    name = naming.render(
        "{keyword}_{source}_{op}_{date}_{time}",
        op="cleaned",
        keyword="visa",
        source="VIP group",
        now=MOMENT,
    )
    assert name == "visa_VIP_group_cleaned_2026-09-17_2051.txt"


def test_name_is_sanitized() -> None:
    assert naming.sanitize_stem("my cards / report") == "my_cards_report"
    assert naming.sanitize_stem("???") == "file"
    assert naming.render("bad*name", op="cleaned") == "badname.txt"


def test_extension_is_not_duplicated() -> None:
    assert naming.render("already.txt", op="cleaned") == "already.txt"


def test_suffix_default_override_and_clear() -> None:
    naming.set_suffix(None)
    assert naming.suffix() == naming.DEFAULT_SUFFIX
    naming.set_suffix("@MyTag")
    assert naming.suffix() == "@MyTag"
    naming.set_suffix("")
    assert naming.suffix() == ""
    naming.set_suffix(None)


async def test_output_name_uses_saved_template(db) -> None:
    await prefs.save_prefs(11, {"filename": "mycards_{op}"})
    assert await naming.output_name(11, "cleaned") == "mycards_cleaned.txt"


async def test_one_shot_override_is_consumed_once(db) -> None:
    data = await prefs.load_prefs(12)
    data["filename"] = "base_{op}"
    data["filename_once"] = "special"
    await prefs.save_prefs(12, data)

    assert await naming.output_name(12, "cleaned") == "special.txt"
    assert await naming.output_name(12, "cleaned") == "base_cleaned.txt"


async def test_output_names_renders_all_parts_from_one_template(db) -> None:
    await prefs.save_prefs(13, {"filename": "{op}_{index}"})
    names = await naming.output_names(13, "part", [1, 2, 3])
    assert names == ["part_1.txt", "part_2.txt", "part_3.txt"]
