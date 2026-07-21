import logging
import time
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import types

from app.models.article import Extraction
from app.prompts.extraction_v1 import (
    PROMPT_VERSION,
    SYSTEM_INSTRUCTION,
    build_user_message,
)

logger = logging.getLogger(__name__)

# Gemini 2.5 Flash pricing (USD per 1M tokens), late-2025
_PRICE_FLASH_INPUT_PER_M = 0.075
_PRICE_FLASH_OUTPUT_PER_M = 0.30


def _flash_cost(tokens_in: int, tokens_out: int) -> float:
    return (
        tokens_in / 1_000_000 * _PRICE_FLASH_INPUT_PER_M
        + tokens_out / 1_000_000 * _PRICE_FLASH_OUTPUT_PER_M
    )


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
    ) -> None:
        self._model = model
        # Use Vertex AI route — billing flows through GCP project (no separate
        # AI Studio prepayment), auth via ADC (runtime SA needs roles/aiplatform.user).
        self._client = _client or genai.Client(
            vertexai=True,
            project=project,
            location=location,
        )

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
        # response_schema works on Vertex AI (uses different schema serialization
        # than AI Studio path which rejects additional_properties).
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=Extraction,
            temperature=0.1,
            max_output_tokens=2048,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )

        t0 = time.perf_counter()
        response = self._client.models.generate_content(
            model=self._model,
            config=config,
            contents=[user_msg],
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)

        raw_text = str(response.text)
        extraction = Extraction.model_validate_json(raw_text)

        tokens_in = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
        tokens_out = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
        cost = _flash_cost(tokens_in, tokens_out)

        return ExtractionResult(
            extraction=extraction,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            latency_ms=latency_ms,
            prompt_version=PROMPT_VERSION,
            model=self._model,
        )
