from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.errors import AppError
from backend.app.services.ingestion import ParsedCsv, parse_csv

DEMO_ID = "retail_demo"
MAX_TABLES = 3


def _quote_identifier(identifier: str) -> str:
    if not identifier.replace("_", "").isalnum():
        raise ValueError("Unsafe internal identifier")
    return f'"{identifier}"'


class DatasetStore:
    def __init__(self, data_dir: Path, max_upload_mb: int) -> None:
        self.root = data_dir.resolve()
        self.datasets_dir = self.root / "datasets"
        self.metadata_path = self.root / "datasets.json"
        self.max_upload_bytes = max_upload_mb * 1024 * 1024
        self._lock = threading.RLock()
        self.datasets_dir.mkdir(parents=True, exist_ok=True)
        if not self.metadata_path.exists():
            self._write_metadata({})

    def list_datasets(self) -> list[dict[str, Any]]:
        metadata = self._read_metadata()
        return [
            {
                "id": item["id"],
                "name": item["name"],
                "table_count": len(item["tables"]),
                "created_at": item["created_at"],
                "protected": item.get("protected", False),
            }
            for item in sorted(metadata.values(), key=lambda entry: entry["created_at"])
        ]

    def create_dataset(
        self, name: str, *, dataset_id: str | None = None, protected: bool = False
    ) -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise AppError("INVALID_DATASET_NAME", "Dataset name cannot be blank.", 400)
        identifier = dataset_id or str(uuid.uuid4())
        if dataset_id is None:
            self._validate_uuid(identifier)
        with self._lock:
            metadata = self._read_metadata()
            if identifier in metadata:
                raise AppError("DATASET_EXISTS", "The dataset already exists.", 409)
            db_path = self._db_path(identifier)
            sqlite3.connect(db_path).close()
            record = {
                "id": identifier,
                "name": clean_name,
                "created_at": datetime.now(UTC).isoformat(),
                "protected": protected,
                "tables": [],
            }
            metadata[identifier] = record
            self._write_metadata(metadata)
        return record

    def upload_table(self, dataset_id: str, filename: str, content: bytes) -> dict[str, Any]:
        parsed = parse_csv(filename, content, self.max_upload_bytes)
        with self._lock:
            metadata = self._read_metadata()
            dataset = self._get_record(metadata, dataset_id)
            if len(dataset["tables"]) >= MAX_TABLES:
                raise AppError(
                    "TABLE_LIMIT_REACHED", f"Datasets may contain at most {MAX_TABLES} tables.", 422
                )
            if any(table["name"] == parsed.table_name for table in dataset["tables"]):
                raise AppError(
                    "TABLE_EXISTS", "A table with this normalized name already exists.", 409
                )
            self._write_table(self._db_path(dataset_id), parsed)
            table_record = {
                "name": parsed.table_name,
                "source_filename": parsed.source_filename,
                "row_count": len(parsed.rows),
                "columns": [
                    {
                        "name": column.name,
                        "source_name": column.source_name,
                        "type": column.sqlite_type,
                    }
                    for column in parsed.columns
                ],
            }
            dataset["tables"].append(table_record)
            try:
                self._write_metadata(metadata)
            except Exception:
                self._drop_table(self._db_path(dataset_id), parsed.table_name)
                raise
            return table_record

    def schema(self, dataset_id: str) -> dict[str, Any]:
        record = self._get_record(self._read_metadata(), dataset_id)
        return {"id": record["id"], "name": record["name"], "tables": record["tables"]}

    def query_target(self, dataset_id: str) -> tuple[Path, frozenset[str]]:
        """Return only an app-owned database path and its metadata-backed table allowlist."""
        record = self._get_record(self._read_metadata(), dataset_id)
        db_path = self._db_path(dataset_id)
        if db_path.is_symlink() or not db_path.is_file():
            raise AppError("UNSAFE_DATASET_PATH", "Dataset storage is unavailable or unsafe.", 409)
        resolved = db_path.resolve(strict=True)
        if resolved.parent != self.datasets_dir.resolve():
            raise AppError("UNSAFE_DATASET_PATH", "Dataset storage is unavailable or unsafe.", 409)
        return resolved, frozenset(table["name"] for table in record["tables"])

    def preview(self, dataset_id: str, table_name: str, limit: int) -> dict[str, Any]:
        record = self._get_record(self._read_metadata(), dataset_id)
        table = next((item for item in record["tables"] if item["name"] == table_name), None)
        if table is None:
            raise AppError(
                "TABLE_NOT_FOUND", "The requested table does not exist in this dataset.", 404
            )
        db_path = self._db_path(dataset_id)
        connection = sqlite3.connect(db_path)
        try:
            cursor = connection.execute(
                f"SELECT * FROM {_quote_identifier(table_name)} LIMIT ?", (limit,)
            )
            rows = [list(row) for row in cursor.fetchall()]
            columns = [description[0] for description in cursor.description or []]
        finally:
            connection.close()
        return {"table": table_name, "columns": columns, "rows": rows, "limit": limit}

    def delete_dataset(self, dataset_id: str) -> None:
        with self._lock:
            metadata = self._read_metadata()
            record = self._get_record(metadata, dataset_id)
            if record.get("protected"):
                raise AppError(
                    "DATASET_PROTECTED", "The built-in demo dataset cannot be deleted.", 409
                )
            db_path = self._db_path(dataset_id)
            if db_path.is_symlink():
                raise AppError("UNSAFE_DATASET_PATH", "Dataset storage is not safe to delete.", 409)
            db_path.unlink(missing_ok=True)
            del metadata[dataset_id]
            self._write_metadata(metadata)

    def seed_demo(self, sample_data_dir: Path) -> None:
        with self._lock:
            if DEMO_ID in self._read_metadata():
                return
            self.create_dataset("Retail Demo", dataset_id=DEMO_ID, protected=True)
            try:
                for filename in ("customers.csv", "products.csv", "orders.csv"):
                    self.upload_table(DEMO_ID, filename, (sample_data_dir / filename).read_bytes())
            except Exception:
                metadata = self._read_metadata()
                metadata.pop(DEMO_ID, None)
                self._db_path(DEMO_ID).unlink(missing_ok=True)
                self._write_metadata(metadata)
                raise

    def _db_path(self, dataset_id: str) -> Path:
        if dataset_id != DEMO_ID:
            self._validate_uuid(dataset_id)
        candidate = self.datasets_dir / f"{dataset_id}.db"
        if candidate.parent.resolve() != self.datasets_dir.resolve():
            raise AppError("INVALID_DATASET_ID", "Dataset ID is invalid.", 404)
        return candidate

    @staticmethod
    def _validate_uuid(dataset_id: str) -> None:
        try:
            parsed = uuid.UUID(dataset_id)
        except (ValueError, AttributeError) as exc:
            raise AppError("INVALID_DATASET_ID", "Dataset ID is invalid.", 404) from exc
        if str(parsed) != dataset_id:
            raise AppError("INVALID_DATASET_ID", "Dataset ID is invalid.", 404)

    @staticmethod
    def _get_record(metadata: dict[str, Any], dataset_id: str) -> dict[str, Any]:
        if dataset_id != DEMO_ID:
            DatasetStore._validate_uuid(dataset_id)
        try:
            return metadata[dataset_id]
        except KeyError as exc:
            raise AppError(
                "DATASET_NOT_FOUND", "The requested dataset does not exist.", 404
            ) from exc

    def _read_metadata(self) -> dict[str, Any]:
        try:
            return json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise RuntimeError("Dataset metadata is unavailable") from exc

    def _write_metadata(self, metadata: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(prefix="datasets-", suffix=".json", dir=self.root)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(metadata, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.metadata_path)
        finally:
            Path(temp_name).unlink(missing_ok=True)

    @staticmethod
    def _write_table(db_path: Path, parsed: ParsedCsv) -> None:
        columns_sql = ", ".join(
            f"{_quote_identifier(column.name)} {column.sqlite_type}" for column in parsed.columns
        )
        placeholders = ", ".join("?" for _ in parsed.columns)
        connection = sqlite3.connect(db_path)
        try:
            with connection:
                connection.execute(
                    f"CREATE TABLE {_quote_identifier(parsed.table_name)} ({columns_sql})"
                )
                if parsed.rows:
                    insert_sql = (
                        f"INSERT INTO {_quote_identifier(parsed.table_name)} "
                        f"VALUES ({placeholders})"
                    )
                    connection.executemany(
                        insert_sql,
                        parsed.rows,
                    )
        except sqlite3.Error as exc:
            raise AppError("INGESTION_FAILED", "The CSV table could not be stored.", 422) from exc
        finally:
            connection.close()

    @staticmethod
    def _drop_table(db_path: Path, table_name: str) -> None:
        connection = sqlite3.connect(db_path)
        try:
            with connection:
                connection.execute(f"DROP TABLE IF EXISTS {_quote_identifier(table_name)}")
        finally:
            connection.close()
