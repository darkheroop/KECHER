from pathlib import Path

from bot.services.text_ops import (
    CleanOptions,
    clean_file,
    count_lines,
    dedup_file,
    merge_files,
    split_file,
)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_split_by_lines(tmp_path: Path) -> None:
    src = _write(tmp_path / "data.txt", "".join(f"{i}\n" for i in range(10)))
    result = split_file(src, tmp_path / "out", mode="lines", value=3)
    assert [p.name for p in result.files] == [
        "data_001.txt",
        "data_002.txt",
        "data_003.txt",
        "data_004.txt",
    ]
    assert result.lines == 10
    assert count_lines(result.files[0]) == 3
    assert count_lines(result.files[3]) == 1


def test_split_by_parts(tmp_path: Path) -> None:
    src = _write(tmp_path / "data.txt", "".join(f"{i}\n" for i in range(10)))
    result = split_file(src, tmp_path / "out", mode="parts", value=3)
    assert len(result.files) == 3
    assert sum(count_lines(p) for p in result.files) == 10


def test_split_by_size(tmp_path: Path) -> None:
    lines = "".join("abcdefghij\n" for _ in range(10))  # 11 bytes each
    src = _write(tmp_path / "data.txt", lines)
    result = split_file(src, tmp_path / "out", mode="size", value=25)
    assert len(result.files) >= 3
    assert "".join(p.read_text(encoding="utf-8") for p in result.files) == lines


def test_split_rejects_bad_value(tmp_path: Path) -> None:
    src = _write(tmp_path / "data.txt", "a\n")
    try:
        split_file(src, tmp_path / "out", mode="lines", value=0)
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("value=0 should be rejected")


def test_clean_removes_empty_and_duplicates(tmp_path: Path) -> None:
    src = _write(tmp_path / "in.txt", "a\n\nb\nA\na\n b \n")
    out = tmp_path / "out.txt"
    result = clean_file(
        src, out, CleanOptions(remove_empty=True, trim=True, dedup=True)
    )
    assert result.total == 6
    assert result.empty == 1
    assert result.duplicates == 2
    assert result.passed == 3
    assert out.read_text(encoding="utf-8") == "a\nb\nA\n"


def test_clean_luhn_offline(tmp_path: Path) -> None:
    src = _write(
        tmp_path / "in.txt",
        "4111111111111111|OK\n4242424242424241|BAD\n",
    )
    out = tmp_path / "out.txt"
    result = clean_file(
        src,
        out,
        CleanOptions(separator="|", luhn_field=1, trim=True),
    )
    assert result.passed == 1
    assert result.rejected == 1
    assert "4111111111111111" in out.read_text(encoding="utf-8")


def test_clean_luhn_check_all(tmp_path: Path) -> None:
    src = _write(
        tmp_path / "in.txt",
        "id1 card 4111 1111 1111 1111 ok\n"
        "id2 card 4242 4242 4242 4241 bad\n"
        "id3 no numbers here at all\n"
        "id4 mixed 4111111111111111 and 4242424242424241\n",
    )
    out = tmp_path / "out.txt"
    result = clean_file(src, out, CleanOptions(luhn=True))
    assert result.total == 4
    assert result.luhn_checked == 4
    assert result.luhn_valid == 2
    assert result.luhn_invalid == 2
    assert result.passed == 2
    text = out.read_text(encoding="utf-8")
    assert "id1" in text and "id4" in text
    assert "id2" not in text and "id3" not in text


def test_clean_sort(tmp_path: Path) -> None:
    src = _write(tmp_path / "in.txt", "c\na\nb\n")
    out = tmp_path / "out.txt"
    clean_file(src, out, CleanOptions(trim=False, sort=True))
    assert out.read_text(encoding="utf-8") == "a\nb\nc\n"


def test_dedup_exact_and_normalized(tmp_path: Path) -> None:
    src = _write(tmp_path / "in.txt", "Hello   World\nhello world\n")

    exact_out = tmp_path / "exact.txt"
    exact = dedup_file(src, exact_out, normalize=False)
    assert (exact.original, exact.unique, exact.removed) == (2, 2, 0)

    norm_out = tmp_path / "norm.txt"
    norm = dedup_file(src, norm_out, normalize=True)
    assert (norm.original, norm.unique, norm.removed) == (2, 1, 1)


def test_merge_plain_dedup_sort(tmp_path: Path) -> None:
    a = _write(tmp_path / "a.txt", "1\n2\n")
    b = _write(tmp_path / "b.txt", "2\n3\n")

    plain_out = tmp_path / "plain.txt"
    plain = merge_files([a, b], plain_out)
    assert (plain.files, plain.total, plain.written) == (2, 4, 4)

    dedup_out = tmp_path / "dedup.txt"
    dedup = merge_files([a, b], dedup_out, dedup=True)
    assert dedup.written == 3 and dedup.duplicates == 1

    sort_out = tmp_path / "sort.txt"
    merge_files([a, b], sort_out, sort=True)
    assert sort_out.read_text(encoding="utf-8") == "1\n2\n2\n3\n"
