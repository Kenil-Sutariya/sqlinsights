from __future__ import annotations

import pytest

from backend.app.errors import AppError
from backend.app.services.ingestion import MAX_CELL_CHARS, MAX_COLUMNS, MAX_ROWS, parse_csv


def error_code(filename: str, content: bytes, max_bytes: int = 5 * 1024 * 1024) -> str:
    with pytest.raises(AppError) as caught:
        parse_csv(filename, content, max_bytes)
    return caught.value.code


@pytest.mark.parametrize(
    ("filename", "content", "expected"),
    [
        ("data.txt", b"a,b\n1,2\n", "UNSUPPORTED_FILE_TYPE"),
        ("data.csv", b"", "EMPTY_CSV"),
        ("data.csv", b"\xff\xfe", "INVALID_ENCODING"),
        ("data.csv", b"a;b\n1;2\n", "WRONG_DELIMITER"),
        ("data.csv", b"First Name,first-name\nA,B\n", "DUPLICATE_HEADERS"),
        ("data.csv", b"a,b\n1\n", "MALFORMED_ROWS"),
    ],
)
def test_invalid_csv_cases(filename: str, content: bytes, expected: str) -> None:
    assert error_code(filename, content) == expected


def test_bom_and_conservative_types() -> None:
    content = (
        "\ufeffPostal Code,Count,Price,When\n00123,2,2.50,2026-10-01\n00456,,3.00,2026-10-02\n"
    ).encode()
    parsed = parse_csv(
        "Odd file.csv",
        content,
        1024,
    )
    assert parsed.table_name == "odd_file"
    assert [(column.name, column.sqlite_type) for column in parsed.columns] == [
        ("postal_code", "TEXT"),
        ("count", "INTEGER"),
        ("price", "REAL"),
        ("when", "TEXT"),
    ]
    assert parsed.rows[0] == ["00123", 2, 2.5, "2026-10-01"]


def test_enforced_limits() -> None:
    assert error_code("x.csv", b"a,b\n1,2\n", 3) == "UPLOAD_TOO_LARGE"
    too_many_columns = ((",".join(f"c{i}" for i in range(MAX_COLUMNS + 1))) + "\n").encode()
    assert error_code("x.csv", too_many_columns) == "TOO_MANY_COLUMNS"
    oversized_cell = f"value\n{'x' * (MAX_CELL_CHARS + 1)}\n".encode()
    assert error_code("x.csv", oversized_cell) == "CELL_TOO_LARGE"
    too_many_rows = ("value\n" + "1\n" * (MAX_ROWS + 1)).encode()
    assert error_code("x.csv", too_many_rows, len(too_many_rows) + 1) == "TOO_MANY_ROWS"
