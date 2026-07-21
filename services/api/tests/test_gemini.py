from unittest.mock import MagicMock, patch

import pytest
from google.genai import types
from google.genai.errors import ClientError

from app.models.article import Extraction, Sentiment
from app.services.gemini import (
    ExtractionResult,
    ExtractionTruncatedError,
    GeminiExtractor,
)


@pytest.fixture
def fake_response_json() -> str:
    return (
        '{"title":"t","summary":"s","tickers":["AAPL"],'
        '"sentiment":{"score":0.5,"label":"bullish"},'
        '"core_thesis":"c","categories":[],"entities":[],"language":"en"}'
    )


def test_extract_parses_response_into_pydantic(fake_response_json: str) -> None:
    fake_response = MagicMock()
    fake_response.text = fake_response_json
    fake_response.usage_metadata.prompt_token_count = 100
    fake_response.usage_metadata.candidates_token_count = 50

    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = fake_response

    extractor = GeminiExtractor(model="gemini-2.5-flash", _client=fake_client)
    result: ExtractionResult = extractor.extract(
        source="wsj",
        url="https://x",
        published_at="2026-04-24T13:30:00Z",
        clean_text="Apple beat earnings.",
    )

    assert result.extraction.tickers == ["AAPL"]
    assert result.extraction.sentiment == Sentiment(score=0.5, label="bullish")
    assert result.tokens_in == 100
    assert result.tokens_out == 50
    assert result.cost_usd > 0
    assert result.latency_ms >= 0
    assert result.prompt_version == "v2"

    config = fake_client.models.generate_content.call_args.kwargs["config"]
    assert config.response_mime_type == "application/json"
    assert config.max_output_tokens == 4096
    assert config.response_schema is Extraction
    schema = config.response_schema.model_json_schema()
    assert schema["properties"]["tickers"]["maxItems"] == 12
    assert schema["properties"]["categories"]["maxItems"] == 8
    assert schema["properties"]["entities"]["maxItems"] == 20


def test_extract_reports_max_tokens_without_blind_retry() -> None:
    truncated = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                finish_reason=types.FinishReason.MAX_TOKENS,
            )
        ],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=100,
            candidates_token_count=4096,
        ),
    )
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = truncated

    with pytest.raises(ExtractionTruncatedError, match="max_output_tokens=4096"):
        GeminiExtractor(_client=fake_client).extract(
            source="hn",
            url="https://x",
            published_at="2026-07-21T00:00:00Z",
            clean_text="Long article",
        )

    fake_client.models.generate_content.assert_called_once()


def test_extract_reports_missing_structured_text_without_retry() -> None:
    empty = types.GenerateContentResponse(candidates=[])
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = empty

    with pytest.raises(RuntimeError, match="no structured response text"):
        GeminiExtractor(_client=fake_client).extract(
            source="hn",
            url="https://x",
            published_at="2026-07-21T00:00:00Z",
            clean_text="Article",
        )

    fake_client.models.generate_content.assert_called_once()


def test_extract_retries_vertex_429_once(fake_response_json: str) -> None:
    valid = MagicMock()
    valid.text = fake_response_json
    valid.usage_metadata.prompt_token_count = 100
    valid.usage_metadata.candidates_token_count = 50
    fake_client = MagicMock()
    fake_client.models.generate_content.side_effect = [
        ClientError(429, {"error": {"message": "rate limited"}}),
        valid,
    ]
    sleep = MagicMock()

    result = GeminiExtractor(_client=fake_client, _sleep=sleep).extract(
        source="hn",
        url="https://x",
        published_at="2026-07-21T00:00:00Z",
        clean_text="Article",
    )

    assert result.extraction.title == "t"
    assert fake_client.models.generate_content.call_count == 2
    configs = [call.kwargs["config"] for call in fake_client.models.generate_content.call_args_list]
    assert [config.max_output_tokens for config in configs] == [4096, 4096]
    sleep.assert_called_once_with(1.0)


def test_client_uses_vertex_adc_without_api_key() -> None:
    with patch("app.services.gemini.genai.Client") as client_cls:
        GeminiExtractor(
            model="gemini-2.5-flash",
            project="test-project",
            location="us-east1",
        )

    client_cls.assert_called_once_with(
        vertexai=True,
        project="test-project",
        location="us-east1",
    )


def test_health_check_calls_vertex_model_endpoint() -> None:
    fake_response = MagicMock()
    fake_response.total_tokens = 6
    fake_client = MagicMock()
    fake_client.models.count_tokens.return_value = fake_response

    extractor = GeminiExtractor(model="gemini-2.5-flash", _client=fake_client)
    extractor.check_health()

    fake_client.models.count_tokens.assert_called_once_with(
        model="gemini-2.5-flash",
        contents="Auralee Vertex AI health check",
    )


def test_health_check_rejects_empty_vertex_response() -> None:
    fake_response = MagicMock()
    fake_response.total_tokens = None
    fake_client = MagicMock()
    fake_client.models.count_tokens.return_value = fake_response

    extractor = GeminiExtractor(model="gemini-2.5-flash", _client=fake_client)

    with pytest.raises(RuntimeError, match="returned no token count"):
        extractor.check_health()
