import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models.run import Run, RunError
from app.services.firestore_repo import FirestoreRepo
from app.services.judge import GeminiJudge

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_HOURS = 72
DEFAULT_BATCH_SIZE = 20


async def run_eval_judge(
    repo: FirestoreRepo,
    judge: GeminiJudge,
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
    limit: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any]:
    run = Run(id="", kind="eval-judge", started_at=datetime.now(UTC))
    after = datetime.now(UTC) - timedelta(hours=lookback_hours)
    articles = repo.list_articles_needing_judge(processed_after=after, limit=limit)
    run.articles_attempted = len(articles)

    for article in articles:
        # We store `clean_text_chars` only; reuse summary + core_thesis + title as judgeable surface.
        # If you want full-fidelity judging, fetch raw HTML from GCS here — deferred for now.
        proxy_text = (
            f"TITLE: {article.title}\n\n"
            f"SUMMARY: {article.summary}\n\n"
            f"CORE_THESIS: {article.core_thesis}"
        )
        extraction_snapshot = {
            "tickers": article.tickers,
            "sentiment": article.sentiment.model_dump(),
            "entities": [e.model_dump() for e in article.entities],
            "language": article.language,
        }

        try:
            result = judge.judge(
                article_url=article.url,
                clean_text=proxy_text,
                extraction_json=str(extraction_snapshot),
            )
        except Exception as e:
            run.errors.append(RunError(url=article.url, stage="judge", message=str(e)[:200]))
            continue

        try:
            repo.update_article_eval_score(article.id, result.eval_score)
            run.articles_ingested += 1  # reuse counter for "judged"
            run.cost_usd += result.cost_usd
        except Exception as e:
            run.errors.append(RunError(url=article.url, stage="write", message=str(e)[:200]))

    run.finished_at = datetime.now(UTC)
    run.status = (
        "partial"
        if run.errors and run.articles_ingested > 0
        else "failure"
        if run.errors
        else "success"
    )
    repo.save_run(run)
    return {
        "status": run.status,
        "judged": run.articles_ingested,
        "errors": len(run.errors),
        "cost_usd": round(run.cost_usd, 6),
    }
