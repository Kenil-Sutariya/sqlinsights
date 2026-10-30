from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    project_root = Path(__file__).resolve().parents[1]
    settings = Settings(
        data_dir=tmp_path / "data",
        sample_data_dir=project_root / "sample_data",
        max_upload_mb=5,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client
