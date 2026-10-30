from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.app.agent.demo import DemoSQLProvider
from backend.app.agent.graph import SQLAgent
from backend.app.agent.providers import OpenAISQLProvider, SQLProvider
from backend.app.api.ask import router as ask_router
from backend.app.api.datasets import router as datasets_router
from backend.app.config import Settings
from backend.app.errors import AppError
from backend.app.schemas import HealthResponse
from backend.app.services.dataset_store import DatasetStore
from backend.app.services.query_executor import QueryExecutor


def create_app(
    settings: Settings | None = None,
    *,
    provider: SQLProvider | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        store = DatasetStore(resolved_settings.data_dir, resolved_settings.max_upload_mb)
        store.seed_demo(resolved_settings.sample_data_dir)
        executor = QueryExecutor(
            store,
            max_result_rows=resolved_settings.max_result_rows,
            timeout_seconds=resolved_settings.query_timeout_seconds,
            max_sql_length=resolved_settings.max_sql_length,
        )
        selected_provider = provider or _build_provider(resolved_settings)
        application.state.dataset_store = store
        application.state.sql_agent = SQLAgent(
            store=store,
            executor=executor,
            provider=selected_provider,
            mode=resolved_settings.ai_mode,
        )
        yield

    application = FastAPI(title="SQLInsights API", version="0.1.0", lifespan=lifespan)

    @application.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "status": "error",
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "request_id": str(uuid.uuid4()),
                },
            },
        )

    @application.exception_handler(RequestValidationError)
    async def handle_request_validation(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "The request payload is invalid.",
                    "request_id": str(uuid.uuid4()),
                },
            },
        )

    @application.get("/health", response_model=HealthResponse)
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": resolved_settings.ai_mode}

    application.include_router(datasets_router)
    application.include_router(ask_router)
    return application


def _build_provider(settings: Settings) -> SQLProvider:
    if settings.ai_mode == "demo":
        return DemoSQLProvider()
    if settings.ai_mode == "llm":
        return OpenAISQLProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            timeout_seconds=settings.openai_timeout_seconds,
        )
    raise ValueError("AI_MODE must be either 'demo' or 'llm'")


app = create_app()
