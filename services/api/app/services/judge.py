import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from google import genai
from google.genai import types

from app.models.article import EvalScore
from app.prompts.judge_v1 import (
    JUDGE_PROMPT_VERSION,
    JUDGE_SYSTEM_INSTRUCTION,
    build_judge_user_message,
)

# Gemini 2.5 Pro pricing (USD per 1M tokens), late-2025
_PRICE_PRO_INPUT_PER_M = 1.25
_PRICE_PRO_OUTPUT_PER_M = 5.00


def _pro_cost(tokens_in: int, tokens_out: int) -> float:
    return (
        tokens_in / 1_000_000 * _PRICE_PRO_INPUT_PER_M
        + tokens_out / 1_000_000 * _PRICE_PRO_OUTPUT_PER_M
    )


@dataclass
class JudgeResult:
    eval_score: EvalScore
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int


class GeminiJudge:
    def __init__(
        self,
        model: str = "gemini-2.5-pro",
        project: str | None = None,
        location: str = "us-east1",
        _client: Any | None = None,
    ) -> None:
        self._model = model
        # Vertex AI route — see GeminiExtractor for rationale.
        self._client = _client or genai.Client(
            vertexai=True,
            project=project,
            location=location,
        )

    def judge(self, *, article_url: str, clean_text: str, extraction_json: str) -> JudgeResult:
        user_msg = build_judge_user_message(article_url, clean_text, extraction_json)
        config = types.GenerateContentConfig(
            system_instruction=JUDGE_SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            temperature=0.1,
            max_output_tokens=2048,
        )
        t0 = time.perf_counter()
        response = self._client.models.generate_content(
            model=self._model,
            config=config,
            contents=[user_msg],
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)

        raw = json.loads(str(response.text))
        eval_score = EvalScore(
            score=float(raw["score"]),
            judge_model=self._model,
            judged_at=datetime.now(UTC),
            issues=list(raw.get("issues", [])),
            reasoning=str(raw.get("reasoning", "")),
        )

        tokens_in = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
        tokens_out = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
        return JudgeResult(
            eval_score=eval_score,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=_pro_cost(tokens_in, tokens_out),
            latency_ms=latency_ms,
        )


__all__ = ["JUDGE_PROMPT_VERSION", "GeminiJudge", "JudgeResult"]
