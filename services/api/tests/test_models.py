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
from app.models.candidate import Candidate
from app.models.ingest import IngestPayload, RawHtml, RawText
from app.models.price import DailyOHLC, Price
from app.models.run import Run, RunError


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


def test_extraction_collection_limits() -> None:
    base = {
        "title": "t",
        "summary": "s",
        "sentiment": Sentiment(score=0.0, label="neutral"),
        "core_thesis": "c",
        "language": "en",
    }
    entities = [Entity(type="person", name=f"Person {index}") for index in range(20)]

    Extraction(**base, tickers=[f"T{index}" for index in range(12)])
    Extraction(**base, categories=[f"c{index}" for index in range(8)])
    Extraction(**base, entities=entities)

    with pytest.raises(ValidationError):
        Extraction(**base, tickers=[f"T{index}" for index in range(13)])
    with pytest.raises(ValidationError):
        Extraction(**base, categories=[f"c{index}" for index in range(9)])
    with pytest.raises(ValidationError):
        Extraction(
            **base,
            entities=[*entities, Entity(type="person", name="Overflow")],
        )


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
    assert a.raw_content_gcs_uri == "gs://bucket/x.html"
    assert a.raw_html_gcs_uri == "gs://bucket/x.html"
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


def test_price_and_daily_ohlc() -> None:
    Price(
        ticker="AAPL",
        name="Apple Inc.",
        exchange="NASDAQ",
        currency="USD",
        first_seen_at=datetime.now(UTC),
        last_refreshed_at=datetime.now(UTC),
        is_active=True,
    )
    DailyOHLC(
        date="2026-04-24",
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=100,
        adj_close=1.5,
        fetched_at=datetime.now(UTC),
        source="yfinance",
    )


def test_daily_ohlc_rejects_malformed_date() -> None:
    with pytest.raises(ValidationError):
        DailyOHLC(
            date="not-a-date",
            open=1.0,
            high=2.0,
            low=0.5,
            close=1.5,
            volume=100,
            adj_close=1.5,
            fetched_at=datetime.now(UTC),
            source="yfinance",
        )
    with pytest.raises(ValidationError):
        DailyOHLC(
            date="2026-13-99",
            open=1.0,
            high=2.0,
            low=0.5,
            close=1.5,
            volume=100,
            adj_close=1.5,
            fetched_at=datetime.now(UTC),
            source="yfinance",
        )


def test_run_with_errors() -> None:
    r = Run(
        id="abc",
        kind="scrape",
        source="wsj",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        status="partial",
        articles_attempted=10,
        articles_ingested=8,
        articles_skipped_dup=1,
        errors=[RunError(url="u", stage="fetch", message="403")],
        cost_usd=0.01,
    )
    assert r.kind == "scrape"
    assert len(r.errors) == 1


def test_ingest_payload_html_variant() -> None:
    published_at = datetime(2026, 4, 23, 23, 55, tzinfo=UTC)
    p = IngestPayload(
        source="wsj",
        source_id="x",
        url="https://x",
        published_at=published_at,
        fetched_at=datetime.now(UTC),
        raw=RawHtml(kind="html", html="<html></html>", encoding="utf-8"),
    )
    assert p.raw.kind == "html"
    assert p.published_at == published_at


def test_ingest_payload_text_variant() -> None:
    p = IngestPayload(
        source="hn",
        source_id="x",
        url="https://x",
        fetched_at=datetime.now(UTC),
        raw=RawText(kind="text", title="t", body="b", metadata={}),
    )
    assert p.raw.kind == "text"
    assert p.published_at is None


def test_candidate_minimal() -> None:
    c = Candidate(source_id="x", url="https://x")
    assert c.title is None
    assert c.published_at is None
