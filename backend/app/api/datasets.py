from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Query, Request, UploadFile

from backend.app.schemas import (
    DatasetCreate,
    DatasetSchema,
    DatasetSummary,
    DeleteResponse,
    PreviewResponse,
    TableInfo,
)
from backend.app.services.dataset_store import DatasetStore

router = APIRouter(prefix="/api/v1/datasets", tags=["datasets"])


def _store(request: Request) -> DatasetStore:
    return request.app.state.dataset_store


@router.get("", response_model=list[DatasetSummary])
def list_datasets(request: Request) -> list[dict]:
    return _store(request).list_datasets()


@router.post("", response_model=DatasetSummary, status_code=201)
def create_dataset(payload: DatasetCreate, request: Request) -> dict:
    record = _store(request).create_dataset(payload.name)
    return {**record, "table_count": 0}


@router.post("/{dataset_id}/tables", response_model=TableInfo, status_code=201)
async def upload_table(
    dataset_id: str,
    request: Request,
    file: Annotated[UploadFile, File()],
) -> dict:
    store = _store(request)
    content = await file.read(store.max_upload_bytes + 1)
    return store.upload_table(dataset_id, file.filename or "", content)


@router.get("/{dataset_id}/schema", response_model=DatasetSchema)
def dataset_schema(dataset_id: str, request: Request) -> dict:
    return _store(request).schema(dataset_id)


@router.get("/{dataset_id}/preview", response_model=PreviewResponse)
def preview_table(
    dataset_id: str,
    request: Request,
    table: str,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> dict:
    return _store(request).preview(dataset_id, table, limit)


@router.delete("/{dataset_id}", response_model=DeleteResponse)
def delete_dataset(dataset_id: str, request: Request) -> dict:
    _store(request).delete_dataset(dataset_id)
    return {"status": "deleted", "dataset_id": dataset_id}
