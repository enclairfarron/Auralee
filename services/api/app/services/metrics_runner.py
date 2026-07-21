import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models.run import Run
from app.services.firestore_repo import FirestoreRepo
from app.services.metrics import aggregate_daily_metrics
from app.sources import P1_SOURCE_KEYS

logger = logging.getLogger(__name__)


async def aggregate_yesterday_metrics(repo: FirestoreRepo) -> dict[str, Any]:
    run = Run(id="", kind="aggregate-metrics", started_at=datetime.now(UTC))
    today = datetime.now(UTC).date()
    yesterday = today - timedelta(days=1)
    start = datetime.combine(yesterday, datetime.min.time(), tzinfo=UTC)
    end = datetime.combine(today, datetime.min.time(), tzinfo=UTC)

    articles = [
        article
        for article in repo.list_articles_in_range(start=start, end=end)
        if article.source in P1_SOURCE_KEYS
    ]
    scrape_runs = [
        scrape_run
        for scrape_run in repo.list_runs_in_range(start=start, end=end, kind="scrape")
        if scrape_run.source in P1_SOURCE_KEYS
    ]
    metrics = aggregate_daily_metrics(
        articles,
        date_str=yesterday.strftime("%Y-%m-%d"),
        scrape_runs=scrape_runs,
    )
    repo.save_metrics(yesterday.strftime("%Y%m%d"), metrics)

    # Update is_active for tickers (30-day window)
    window_start = datetime.now(UTC) - timedelta(days=30)
    recent = repo.list_articles_in_range(start=window_start, end=datetime.now(UTC))
    seen: set[str] = set()
    for a in recent:
        seen.update(a.tickers)
    for t in repo.list_all_tickers():
        repo.set_ticker_active(t, t in seen)

    run.finished_at = datetime.now(UTC)
    run.articles_attempted = len(articles)
    repo.save_run(run)
    return {"status": "success", "metrics": metrics, "active_tickers": len(seen)}
