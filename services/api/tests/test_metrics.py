from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app.models.article import (
    Article,
    EvalScore,
    GeminiMeta,
    SanityCheck,
    Sentiment,
)
from app.models.run import Run, RunError
from app.services.metrics import aggregate_daily_metrics
from app.services.metrics_runner import aggregate_yesterday_metrics


def _article(
    *,
    article_id: str,
    source: str,
    tickers: list[str],
    sentiment_label: str,
    sanity_pass: bool,
    judge_score: float | None,
    cost: float,
) -> Article:
    now = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    return Article(
        id=article_id,
        source=source,  # type: ignore[arg-type]
        source_id="x",
        url=f"https://x/{article_id}",
        title="t",
        published_at=now,
        fetched_at=now,
        processed_at=now,
        language="en",
        summary="s",
        tickers=tickers,
        sentiment=Sentiment(score=0.0, label=sentiment_label),  # type: ignore[arg-type]
        core_thesis="c",
        gemini_meta=GeminiMeta(
            model="gemini-2.5-flash",
            tokens_in=10,
            tokens_out=5,
            cost_usd=cost,
            latency_ms=200,
            prompt_version="v1",
        ),
        sanity_check=SanityCheck(
            ticker_precision_pass=sanity_pass,
            checked_at=now,
            flags=[],
        ),
        eval_score=None
        if judge_score is None
        else EvalScore(
            score=judge_score,
            judge_model="gemini-2.5-pro",
            judged_at=now,
            issues=[],
            reasoning="r",
        ),
    )


def test_aggregate_counts_by_source_and_sentiment() -> None:
    arts = [
        _article(
            article_id="hn_1",
            source="hn",
            tickers=["AAPL"],
            sentiment_label="bullish",
            sanity_pass=True,
            judge_score=8.0,
            cost=0.0001,
        ),
        _article(
            article_id="hn_2",
            source="hn",
            tickers=[],
            sentiment_label="neutral",
            sanity_pass=True,
            judge_score=7.0,
            cost=0.0002,
        ),
        _article(
            article_id="wsj_1",
            source="wsj",
            tickers=["AAPL"],
            sentiment_label="bearish",
            sanity_pass=False,
            judge_score=9.0,
            cost=0.0003,
        ),
    ]
    metrics = aggregate_daily_metrics(arts, date_str="2026-04-24")
    assert metrics["articles_total"] == 3
    assert metrics["by_source"] == {"hn": 2, "wsj": 1}
    assert metrics["by_sentiment"] == {"bullish": 1, "neutral": 1, "bearish": 1}
    assert metrics["m2_precision_pass_rate"] == pytest.approx(2 / 3)
    assert metrics["m3_avg_score"] == pytest.approx((8 + 7 + 9) / 3)
    assert metrics["ticker_extraction_rate"] == pytest.approx(2 / 3)
    assert metrics["unique_tickers_seen"] == 1


def test_aggregate_disagreement_rate() -> None:
    arts = [
        # M2 fail + M3 high: judge missed the issue
        _article(
            article_id="a",
            source="hn",
            tickers=["FAKE"],
            sentiment_label="neutral",
            sanity_pass=False,
            judge_score=8.5,
            cost=0.0001,
        ),
        # M2 pass + M3 low: judge sees something M2 doesn't
        _article(
            article_id="b",
            source="hn",
            tickers=["AAPL"],
            sentiment_label="bullish",
            sanity_pass=True,
            judge_score=3.0,
            cost=0.0001,
        ),
        # Agreement: both pass
        _article(
            article_id="c",
            source="hn",
            tickers=["MSFT"],
            sentiment_label="bullish",
            sanity_pass=True,
            judge_score=8.0,
            cost=0.0001,
        ),
    ]
    m = aggregate_daily_metrics(arts, date_str="2026-04-24")
    assert m["m2_m3_disagreement_count"] == 2
    assert m["m2_m3_disagreement_rate"] == pytest.approx(2 / 3)


def test_aggregate_handles_empty_articles_safely() -> None:
    m = aggregate_daily_metrics([], date_str="2026-04-24")
    assert m["articles_total"] == 0
    assert m["m2_precision_pass_rate"] == 0.0
    assert m["m3_avg_score"] == 0.0
    assert m["scrape_funnel"]["runs_total"] == 0


def test_aggregate_uses_scrape_runs_for_error_and_funnel_metrics() -> None:
    now = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    runs = [
        Run(
            id="success",
            kind="scrape",
            source="hn",
            started_at=now,
            status="success",
            articles_attempted=5,
            articles_ingested=2,
            articles_skipped_dup=1,
            articles_skipped_short=1,
            outcome_counts_complete=True,
            errors=[RunError(stage="fetch", message="timeout")],
        ),
        Run(
            id="partial",
            kind="scrape",
            source="reuters",
            started_at=now,
            status="partial",
            articles_attempted=2,
            articles_skipped_dup=1,
            outcome_counts_complete=True,
            errors=[RunError(stage="ingest", message="Vertex error")],
        ),
        Run(
            id="failure",
            kind="scrape",
            source="reuters",
            started_at=now,
            status="failure",
            outcome_counts_complete=True,
            errors=[RunError(stage="list_candidates", message="feeds unavailable")],
        ),
    ]

    metrics = aggregate_daily_metrics([], date_str="2026-04-24", scrape_runs=runs)

    assert metrics["ingest_errors_total"] == 1
    assert metrics["pipeline_errors_total"] == 3
    assert metrics["scrape_funnel"] == {
        "runs_total": 3,
        "runs_failed_total": 1,
        "candidates_total": 7,
        "ingested_total": 2,
        "duplicates_total": 2,
        "skipped_short_total": 1,
        "fetch_errors_total": 1,
        "ingest_errors_total": 1,
        "list_errors_total": 1,
        "pipeline_errors_total": 3,
        "unclassified_total": 0,
        "overclassified_total": 0,
        "outcome_counts_complete": True,
    }


def test_aggregate_marks_legacy_scrape_outcomes_incomplete() -> None:
    run = Run(
        id="legacy",
        kind="scrape",
        source="hn",
        started_at=datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
        articles_attempted=1,
        articles_ingested=1,
    )

    metrics = aggregate_daily_metrics([], date_str="2026-04-24", scrape_runs=[run])

    assert metrics["scrape_funnel"]["outcome_counts_complete"] is False


@pytest.mark.asyncio
async def test_metrics_runner_reads_scrape_runs_for_same_utc_window() -> None:
    repo = MagicMock()
    repo.list_articles_in_range.side_effect = [[], []]
    repo.list_runs_in_range.return_value = []
    repo.list_all_tickers.return_value = []

    result = await aggregate_yesterday_metrics(repo)

    run_call = repo.list_runs_in_range.call_args
    assert run_call.kwargs["kind"] == "scrape"
    assert run_call.kwargs["start"].tzinfo is UTC
    assert run_call.kwargs["end"].tzinfo is UTC
    assert run_call.kwargs["end"] > run_call.kwargs["start"]
    saved_metrics = repo.save_metrics.call_args.args[1]
    assert saved_metrics["scrape_funnel"]["runs_total"] == 0
    assert result["metrics"] == saved_metrics
