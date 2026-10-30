from __future__ import annotations

from fastapi import APIRouter, Request

from backend.app.agent.graph import SQLAgent
from backend.app.errors import AppError
from backend.app.schemas import AskRequest, AskResponse

router = APIRouter(prefix="/api/v1", tags=["questions"])


@router.post("/ask", response_model=AskResponse)
def ask_question(payload: AskRequest, request: Request) -> dict:
    agent: SQLAgent = request.app.state.sql_agent
    response = agent.ask(payload.dataset_id, payload.question)
    if response.error is not None:
        raise AppError(
            response.error.code,
            response.error.message,
            response.error.status_code,
        )
    return response.model_dump(exclude={"error"})
