from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.models.article import EvalScore, Sentiment
from app.services.judge import JudgeResult
from app.services.judge_runner import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_LOOKBACK_HOURS,
    run_eval_judge,
)


def _article(*, archive_uri: str | None = "gs://raw-bucket/hn/article.json") -> SimpleNamespace:
    return SimpleNamespace(
        id="article-1",
        url="https://example.com/article-1",
        raw_content_gcs_uri=archive_uri,
        raw_html_gcs_uri=None,
        title="Apple beats expectations",
        summary="Apple reported stronger revenue.",
        tickers=["AAPL"],
        sentiment=Sentiment(score=0.7, label="bullish"),
        core_thesis="Apple's revenue beat expectations.",
        categories=["earnings"],
        entities=[],
        language="en",
    )


def _judge_result() -> JudgeResult:
    return JudgeResult(
        eval_score=EvalScore(
            score=9.0,
            judge_model="test-judge",
            judged_at=datetime.now(UTC),
            issues=[],
            reasoning="Accurate extraction.",
        ),
        tokens_in=10,
        tokens_out=5,
        cost_usd=0.001,
        latency_ms=5,
    )


@pytest.mark.asyncio
async def test_default_batch_is_bounded_and_looks_back_for_backlog() -> None:
    repo = MagicMock()
    repo.list_articles_needing_judge.return_value = []
    before = datetime.now(UTC)

    result = await run_eval_judge(repo=repo, judge=MagicMock())

    after = datetime.now(UTC)
    call = repo.list_articles_needing_judge.call_args
    assert call.kwargs["limit"] == DEFAULT_BATCH_SIZE == 20
    processed_after = call.kwargs["processed_after"]
    assert before - timedelta(hours=DEFAULT_LOOKBACK_HOURS) <= processed_after
    assert processed_after <= after - timedelta(hours=DEFAULT_LOOKBACK_HOURS)
    assert result == {"status": "success", "judged": 0, "errors": 0, "cost_usd": 0.0}
    repo.save_run.assert_called_once()


@pytest.mark.asyncio
async def test_judge_uses_injected_archived_content_reader() -> None:
    repo = MagicMock()
    repo.list_articles_needing_judge.return_value = [_article()]
    archive_reader = MagicMock()
    archive_reader.read_clean_text.return_value = "Original Apple article body."
    judge = MagicMock()
    judge.judge.return_value = _judge_result()

    result = await run_eval_judge(repo=repo, judge=judge, archive_reader=archive_reader)

    assert result == {"status": "success", "judged": 1, "errors": 0, "cost_usd": 0.001}
    archive_reader.read_clean_text.assert_called_once_with("gs://raw-bucket/hn/article.json")
    call = judge.judge.call_args.kwargs
    assert call["clean_text"] == "Original Apple article body."
    assert '"summary": "Apple reported stronger revenue."' in call["extraction_json"]
    repo.update_article_eval_score.assert_called_once()


@pytest.mark.asyncio
async def test_missing_archive_is_recorded_without_proxy_fallback() -> None:
    repo = MagicMock()
    repo.list_articles_needing_judge.return_value = [_article(archive_uri=None)]
    archive_reader = MagicMock()
    judge = MagicMock()

    result = await run_eval_judge(repo=repo, judge=judge, archive_reader=archive_reader)

    assert result == {"status": "failure", "judged": 0, "errors": 1, "cost_usd": 0.0}
    archive_reader.read_clean_text.assert_not_called()
    judge.judge.assert_not_called()
    saved_run = repo.save_run.call_args.args[0]
    assert saved_run.errors[0].stage == "archive-read"
    assert saved_run.errors[0].message == "article has no raw content archive URI"


@pytest.mark.asyncio
async def test_archive_read_failure_is_recorded_without_proxy_fallback() -> None:
    repo = MagicMock()
    repo.list_articles_needing_judge.return_value = [_article()]
    archive_reader = MagicMock()
    archive_reader.read_clean_text.side_effect = RuntimeError("GCS object not found")
    judge = MagicMock()

    result = await run_eval_judge(repo=repo, judge=judge, archive_reader=archive_reader)

    assert result == {"status": "failure", "judged": 0, "errors": 1, "cost_usd": 0.0}
    judge.judge.assert_not_called()
    saved_run = repo.save_run.call_args.args[0]
    assert saved_run.errors[0].stage == "archive-read"
    assert saved_run.errors[0].message == (
        "archive reader failed for gs://raw-bucket/hn/article.json: "
        "RuntimeError: GCS object not found"
    )
