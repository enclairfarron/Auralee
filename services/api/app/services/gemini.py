import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import types
from google.genai.errors import ClientError

from app.models.article import Extraction
from app.prompts.extraction_v2 import (
    PROMPT_VERSION,
    SYSTEM_INSTRUCTION,
    build_user_message,
)

logger = logging.getLogger(__name__)

# Gemini 2.5 Flash pricing (USD per 1M tokens), late-2025
_PRICE_FLASH_INPUT_PER_M = 0.075
_PRICE_FLASH_OUTPUT_PER_M = 0.30
_MAX_GENERATION_ATTEMPTS = 2
_MAX_OUTPUT_TOKENS = 4096


class ExtractionTruncatedError(RuntimeError):
    """Raised when Vertex stops a structured extraction at its output limit."""


def _flash_cost(tokens_in: int, tokens_out: int) -> float:
    return (
        tokens_in / 1_000_000 * _PRICE_FLASH_INPUT_PER_M
        + tokens_out / 1_000_000 * _PRICE_FLASH_OUTPUT_PER_M
    )


def _finish_reason(response: Any) -> str | None:
    candidates = getattr(response, "candidates", None)
    if not isinstance(candidates, (list, tuple)) or not candidates:
        return None
    reason = getattr(candidates[0], "finish_reason", None)
    if isinstance(reason, types.FinishReason):
        return reason.value
    return reason if isinstance(reason, str) else None


@dataclass
class ExtractionResult:
    extraction: Extraction
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    prompt_version: str
    model: str


class GeminiExtractor:
    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        project: str | None = None,
        location: str = "us-east1",
        _client: Any | None = None,
        _sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._model = model
        # Use Vertex AI route — billing flows through GCP project (no separate
        # AI Studio prepayment), auth via ADC (runtime SA needs roles/aiplatform.user).
        self._client = _client or genai.Client(
            vertexai=True,
            project=project,
            location=location,
        )
        self._sleep = _sleep

    @property
    def model(self) -> str:
        return self._model

    def check_health(self) -> None:
        """Verify that the configured Vertex model is callable with current ADC.

        ``count_tokens`` reaches the same regional Vertex AI publisher-model
        endpoint as extraction without generating content or incurring generation
        cost.  A local configuration-only check could report healthy while the
        API is disabled, the model/region is invalid, or the runtime service
        account lacks permission.
        """
        response = self._client.models.count_tokens(
            model=self._model,
            contents="Auralee Vertex AI health check",
        )
        total_tokens = getattr(response, "total_tokens", None)
        if not isinstance(total_tokens, int) or total_tokens < 1:
            raise RuntimeError("Vertex AI countTokens returned no token count")

    def extract(
        self,
        *,
        source: str,
        url: str,
        published_at: str,
        clean_text: str,
    ) -> ExtractionResult:
        user_msg = build_user_message(
            source=source,
            url=url,
            published_at=published_at,
            clean_text=clean_text,
        )
        t0 = time.perf_counter()
        for attempt in range(_MAX_GENERATION_ATTEMPTS):
            # response_schema works on Vertex AI (uses different schema serialization
            # than AI Studio path which rejects additional_properties).
            config = types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=Extraction,
                temperature=0.1,
                max_output_tokens=_MAX_OUTPUT_TOKENS,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            )
            try:
                response = self._client.models.generate_content(
                    model=self._model,
                    config=config,
                    contents=[user_msg],
                )
            except ClientError as exc:
                if exc.code != 429 or attempt + 1 >= _MAX_GENERATION_ATTEMPTS:
                    raise
                logger.warning("Vertex extraction rate-limited; retrying once")
                self._sleep(1.0)
                continue

            response_usage = getattr(response, "usage_metadata", None)
            tokens_in = getattr(response_usage, "prompt_token_count", 0) or 0
            tokens_out = getattr(response_usage, "candidates_token_count", 0) or 0
            if _finish_reason(response) == types.FinishReason.MAX_TOKENS.value:
                raise ExtractionTruncatedError(
                    "Vertex extraction reached max_output_tokens="
                    f"{_MAX_OUTPUT_TOKENS} (tokens_out={tokens_out})"
                )
            response_text = getattr(response, "text", None)
            if not isinstance(response_text, str) or not response_text.strip():
                raise RuntimeError("Vertex extraction returned no structured response text")
            extraction = Extraction.model_validate_json(response_text)
            latency_ms = int((time.perf_counter() - t0) * 1000)
            return ExtractionResult(
                extraction=extraction,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=_flash_cost(tokens_in, tokens_out),
                latency_ms=latency_ms,
                prompt_version=PROMPT_VERSION,
                model=self._model,
            )

        raise RuntimeError("Vertex extraction exhausted retries without a response")


__all__ = ["ExtractionResult", "ExtractionTruncatedError", "GeminiExtractor"]
