from unittest.mock import MagicMock, patch

import pytest

from app.models.article import Sentiment
from app.services.gemini import ExtractionResult, GeminiExtractor


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
    assert result.prompt_version == "v1"


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
