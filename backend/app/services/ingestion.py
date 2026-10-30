from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path

from backend.app.errors import AppError

MAX_COLUMNS = 40
MAX_ROWS = 50_000
MAX_CELL_CHARS = 20_000
NULL_VALUES = {"", "null", "none", "na", "n/a"}


@dataclass(frozen=True)
class ParsedColumn:
    name: str
    source_name: str
    sqlite_type: str


@dataclass(frozen=True)
class ParsedCsv:
    table_name: str
    source_filename: str
    columns: list[ParsedColumn]
    rows: list[list[object | None]]


def normalize_identifier(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    if not normalized:
        normalized = fallback
    if normalized[0].isdigit():
        normalized = f"col_{normalized}"
    return normalized[:63]


def parse_csv(filename: str, content: bytes, max_upload_bytes: int) -> ParsedCsv:
    if not filename.lower().endswith(".csv"):
        raise AppError("UNSUPPORTED_FILE_TYPE", "Only .csv files are supported.", 415)
    if not content:
        raise AppError("EMPTY_CSV", "The CSV file is empty.", 422)
    if len(content) > max_upload_bytes:
        raise AppError("UPLOAD_TOO_LARGE", "The CSV file exceeds the upload limit.", 413)
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AppError("INVALID_ENCODING", "CSV files must use UTF-8 encoding.", 422) from exc
    if "\x00" in text:
        raise AppError("INVALID_CSV", "The CSV contains invalid null bytes.", 422)

    stream = io.StringIO(text, newline="")
    try:
        rows = list(csv.reader(stream, delimiter=",", strict=True))
    except csv.Error as exc:
        raise AppError("MALFORMED_CSV", "The CSV could not be parsed.", 422) from exc
    if not rows or not any(cell.strip() for cell in rows[0]):
        raise AppError("MISSING_HEADERS", "The CSV must contain a header row.", 422)
    if len(rows[0]) == 1 and any(delimiter in rows[0][0] for delimiter in (";", "\t", "|")):
        raise AppError("WRONG_DELIMITER", "The CSV must use commas as delimiters.", 422)
    if len(rows[0]) > MAX_COLUMNS:
        raise AppError(
            "TOO_MANY_COLUMNS", f"CSV files may contain at most {MAX_COLUMNS} columns.", 422
        )

    source_headers = [header.strip() for header in rows[0]]
    if any(not header for header in source_headers):
        raise AppError("MISSING_HEADERS", "Every CSV column must have a header.", 422)
    safe_headers = [
        normalize_identifier(header, f"column_{index + 1}")
        for index, header in enumerate(source_headers)
    ]
    if len(set(safe_headers)) != len(safe_headers):
        raise AppError("DUPLICATE_HEADERS", "CSV headers must be unique after normalization.", 422)

    data_rows = rows[1:]
    while data_rows and not any(cell.strip() for cell in data_rows[-1]):
        data_rows.pop()
    if len(data_rows) > MAX_ROWS:
        raise AppError("TOO_MANY_ROWS", f"CSV files may contain at most {MAX_ROWS} rows.", 422)
    for row in data_rows:
        if len(row) != len(source_headers):
            raise AppError(
                "MALFORMED_ROWS", "Every CSV row must have the same number of fields.", 422
            )
        if any(len(cell) > MAX_CELL_CHARS for cell in row):
            raise AppError(
                "CELL_TOO_LARGE", f"CSV cells may contain at most {MAX_CELL_CHARS} characters.", 422
            )

    column_types = [
        _infer_type([row[index] for row in data_rows]) for index in range(len(source_headers))
    ]
    columns = [
        ParsedColumn(name=safe, source_name=source, sqlite_type=sqlite_type)
        for safe, source, sqlite_type in zip(
            safe_headers, source_headers, column_types, strict=True
        )
    ]
    converted_rows = [
        [_convert_value(value, column_types[index]) for index, value in enumerate(row)]
        for row in data_rows
    ]
    table_name = normalize_identifier(Path(filename).stem, "uploaded_table")
    return ParsedCsv(table_name, Path(filename).name, columns, converted_rows)


def _is_null(value: str) -> bool:
    return value.strip().lower() in NULL_VALUES


def _infer_type(values: list[str]) -> str:
    non_null = [value.strip() for value in values if not _is_null(value)]
    if not non_null:
        return "TEXT"
    if any(re.fullmatch(r"-?0\d+", value) for value in non_null):
        return "TEXT"
    if all(re.fullmatch(r"-?(0|[1-9]\d*)", value) for value in non_null):
        return "INTEGER"
    try:
        for value in non_null:
            float(value)
    except ValueError:
        return "TEXT"
    return "REAL"


def _convert_value(value: str, sqlite_type: str) -> object | None:
    stripped = value.strip()
    if _is_null(stripped):
        return None
    if sqlite_type == "INTEGER":
        return int(stripped)
    if sqlite_type == "REAL":
        return float(stripped)
    return stripped
