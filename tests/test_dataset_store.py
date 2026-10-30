from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.errors import AppError
from backend.app.services.dataset_store import DatasetStore


def test_multiple_uploads_table_limit_and_repeat(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path / "data", 5)
    dataset = store.create_dataset("Uploads")
    content = b"id,value\n001,1\n"
    store.upload_table(dataset["id"], "one.csv", content)
    store.upload_table(dataset["id"], "two.csv", content)
    store.upload_table(dataset["id"], "three.csv", content)
    with pytest.raises(AppError, match="at most 3") as caught:
        store.upload_table(dataset["id"], "four.csv", content)
    assert caught.value.code == "TABLE_LIMIT_REACHED"


def test_duplicate_table_is_rejected(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path / "data", 5)
    dataset = store.create_dataset("Uploads")
    store.upload_table(dataset["id"], "sales.csv", b"id\n001\n")
    with pytest.raises(AppError) as caught:
        store.upload_table(dataset["id"], "sales.csv", b"id\n002\n")
    assert caught.value.code == "TABLE_EXISTS"


def test_invalid_ids_and_symlink_deletion_are_safe(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path / "data", 5)
    with pytest.raises(AppError) as caught:
        store.schema("../../outside")
    assert caught.value.code == "INVALID_DATASET_ID"

    dataset = store.create_dataset("Symlink test")
    db_path = store.datasets_dir / f"{dataset['id']}.db"
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    db_path.unlink()
    db_path.symlink_to(outside)
    with pytest.raises(AppError) as caught:
        store.delete_dataset(dataset["id"])
    assert caught.value.code == "UNSAFE_DATASET_PATH"
    assert outside.read_text(encoding="utf-8") == "keep"
