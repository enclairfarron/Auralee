from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.models.article import (
    Article,
    Entity,
    EvalScore,
    Extraction,
    GeminiMeta,
    SanityCheck,
    Sentiment,
)


def test_sentiment_score_must_be_in_range() -> None:
    Sentiment(score=0.5, label="bullish")
    with pytest.raises(ValidationError):
        Sentiment(score=1.5, label="bullish")
    with pytest.raises(ValidationError):
        Sentiment(score=-2.0, label="bearish")


def test_extraction_minimal() -> None:
    e = Extraction(
        title="t",
        summary="s",
        sentiment=Sentiment(score=0.0, label="neutral"),
        core_thesis="c",
        language="en",
    )
    assert e.tickers == []
    assert e.entities == []
    assert e.categories == []


def test_entity_with_optional_ticker() -> None:
    Entity(type="company", name="Apple Inc.", ticker="AAPL")
    Entity(type="person", name="Tim Cook")  # no ticker


def test_article_full_doc() -> None:
    a = Article(
        id="wsj_20260424_a3f1b9d2",
        source="wsj",
        source_id="WP-123",
        url="https://example.com/a",
        title="t",
        published_at=datetime(2026, 4, 24, tzinfo=UTC),
        fetched_at=datetime(2026, 4, 24, tzinfo=UTC),
        processed_at=datetime(2026, 4, 24, tzinfo=UTC),
        language="en",
        raw_html_gcs_uri="gs://bucket/x.html",
        clean_text_chars=100,
        summary="s",
        tickers=["AAPL"],
        sentiment=Sentiment(score=0.5, label="bullish"),
        core_thesis="c",
        gemini_meta=GeminiMeta(
            model="gemini-2.5-flash",
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.0001,
            latency_ms=200,
            prompt_version="v1",
        ),
    )
    assert a.embedding is None  # Week 2 reserved
    assert a.sanity_check is None  # set later in pipeline
    assert a.eval_score is None


def test_sanity_check_default_pass_empty_flags() -> None:
    s = SanityCheck(ticker_precision_pass=True, checked_at=datetime.now(UTC))
    assert s.flags == []


def test_eval_score_with_issues() -> None:
    e = EvalScore(
        score=8.5,
        judge_model="gemini-2.5-pro",
        judged_at=datetime.now(UTC),
        issues=["missing_ticker:TSLA"],
        reasoning="...",
    )
    assert 0 <= e.score <= 10
