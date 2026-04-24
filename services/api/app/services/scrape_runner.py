import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from app.models.run import Run, RunError
from app.services.firestore_repo import FirestoreRepo
from app.services.ingest_service import IngestService
from app.services.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


async def run_scrape(
    scraper: BaseScraper,
    ingest: IngestService,
    repo: FirestoreRepo,
    candidate_limit: int = 50,
    fetch_delay_seconds: float = 0.0,
) -> dict[str, Any]:
    run = Run(id="", kind="scrape", source=scraper.source_name, started_at=datetime.now(UTC))

    try:
        candidates = await scraper.list_candidates(limit=candidate_limit)
    except Exception as e:  # broad: list failures recorded but don't crash cron
        run.status = "failure"
        run.errors.append(RunError(stage="list_candidates", message=str(e)[:200]))
        run.finished_at = datetime.now(UTC)
        repo.save_run(run)
        return _summarize(run)

    run.articles_attempted = len(candidates)

    for c in candidates:
        try:
            payload = await scraper.fetch_one(c)
        except Exception as e:
            run.errors.append(RunError(url=c.url, stage="fetch", message=str(e)[:200]))
            if fetch_delay_seconds > 0:
                await asyncio.sleep(fetch_delay_seconds)
            continue

        try:
            response = ingest.process(payload)
        except Exception as e:
            run.errors.append(RunError(url=c.url, stage="ingest", message=str(e)[:200]))
            if fetch_delay_seconds > 0:
                await asyncio.sleep(fetch_delay_seconds)
            continue

        if response.status == "ingested":
            run.articles_ingested += 1
            if response.meta:
                run.cost_usd += response.meta.cost_usd
        elif response.status == "duplicate":
            run.articles_skipped_dup += 1

        if fetch_delay_seconds > 0:
            await asyncio.sleep(fetch_delay_seconds)

    run.finished_at = datetime.now(UTC)
    if run.errors and run.articles_ingested > 0:
        run.status = "partial"
    elif run.errors and run.articles_ingested == 0:
        run.status = "failure"
    else:
        run.status = "success"

    repo.save_run(run)
    return _summarize(run)


def _summarize(run: Run) -> dict[str, Any]:
    return {
        "kind": run.kind,
        "source": run.source,
        "status": run.status,
        "attempted": run.articles_attempted,
        "ingested": run.articles_ingested,
        "skipped_dup": run.articles_skipped_dup,
        "errors": len(run.errors),
        "cost_usd": round(run.cost_usd, 6),
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }
