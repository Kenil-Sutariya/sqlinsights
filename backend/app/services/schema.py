from __future__ import annotations

from backend.app.errors import AppError
from backend.app.services.dataset_store import DatasetStore


def load_agent_schema(store: DatasetStore, dataset_id: str) -> dict:
    """Return bounded schema metadata for only the selected dataset, never row values."""
    dataset = store.schema(dataset_id)
    tables = [
        {
            "name": table["name"],
            "row_count": table["row_count"],
            "columns": [
                {"name": column["name"], "type": column["type"]} for column in table["columns"]
            ],
        }
        for table in dataset["tables"]
    ]
    if not tables:
        raise AppError("EMPTY_DATASET", "The selected dataset has no tables to query.", 400)
    return {"dataset_id": dataset["id"], "name": dataset["name"], "tables": tables}
