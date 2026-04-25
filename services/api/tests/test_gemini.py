from unittest.mock import MagicMock

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
