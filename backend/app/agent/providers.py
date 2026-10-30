from __future__ import annotations

from typing import Protocol

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)
from pydantic import ValidationError

from backend.app.agent.models import AgentSchema, SQLProposal
from backend.app.agent.prompts import build_provider_input
from backend.app.errors import AppError


class SQLProvider(Protocol):
    def generate(
        self,
        question: str,
        schema: AgentSchema,
        retry_feedback: str | None = None,
    ) -> SQLProposal: ...


class OpenAISQLProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def generate(
        self,
        question: str,
        schema: AgentSchema,
        retry_feedback: str | None = None,
    ) -> SQLProposal:
        if not self.api_key or not self.model:
            raise AppError(
                "PROVIDER_NOT_CONFIGURED",
                "LLM mode requires OPENAI_API_KEY and OPENAI_MODEL.",
                503,
            )
        try:
            client = OpenAI(api_key=self.api_key, timeout=self.timeout_seconds)
            response = client.responses.parse(
                model=self.model,
                input=build_provider_input(question, schema, retry_feedback),
                text_format=SQLProposal,
            )
            parsed = response.output_parsed
            if parsed is None:
                raise AppError(
                    "PROVIDER_MALFORMED_OUTPUT",
                    "The provider did not return a valid SQL proposal.",
                    503,
                    retryable=True,
                )
            return SQLProposal.model_validate(parsed)
        except AppError:
            raise
        except AuthenticationError as exc:
            raise AppError(
                "PROVIDER_AUTH_FAILED",
                "The configured provider credentials were rejected.",
                503,
            ) from exc
        except APITimeoutError as exc:
            raise AppError("PROVIDER_TIMEOUT", "The configured provider timed out.", 503) from exc
        except (APIConnectionError, RateLimitError, APIStatusError) as exc:
            raise AppError(
                "PROVIDER_UNAVAILABLE",
                "The configured provider is currently unavailable.",
                503,
            ) from exc
        except (ValidationError, TypeError, ValueError) as exc:
            raise AppError(
                "PROVIDER_MALFORMED_OUTPUT",
                "The provider returned malformed structured output.",
                503,
                retryable=True,
            ) from exc
