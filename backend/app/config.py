from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    sample_data_dir: Path
    ai_mode: str = "demo"
    max_upload_mb: int = 5
    max_result_rows: int = 200
    query_timeout_seconds: float = 5.0
    max_sql_length: int = 20_000
    openai_api_key: str = ""
    openai_model: str = ""
    openai_timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> Settings:
        project_root = Path(__file__).resolve().parents[2]
        data_dir = Path(os.getenv("DATA_DIR", "./data"))
        if not data_dir.is_absolute():
            data_dir = project_root / data_dir
        return cls(
            data_dir=data_dir.resolve(),
            sample_data_dir=(project_root / "sample_data").resolve(),
            ai_mode=os.getenv("AI_MODE", "demo"),
            max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "5")),
            max_result_rows=int(os.getenv("MAX_RESULT_ROWS", "200")),
            query_timeout_seconds=float(os.getenv("QUERY_TIMEOUT_SECONDS", "5")),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", ""),
            openai_timeout_seconds=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30")),
        )
