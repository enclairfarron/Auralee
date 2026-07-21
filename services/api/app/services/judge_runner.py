import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models.run import Run, RunError
from app.services.archive_reader import (
    ArchivedContentReader,
    ArchiveReadError,
    GCSArchivedContentReader,
)
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
    archive_reader: ArchivedContentReader | None = None,
) -> dict[str, Any]:
    run = Run(id="", kind="eval-judge", started_at=datetime.now(UTC))
    after = datetime.now(UTC) - timedelta(hours=lookback_hours)
    articles = repo.list_articles_needing_judge(processed_after=after, limit=limit)
    run.articles_attempted = len(articles)

    for article in articles:
        archive_uri = article.raw_content_gcs_uri or article.raw_html_gcs_uri
        if not archive_uri:
            run.errors.append(
                RunError(
                    url=article.url,
                    stage="archive-read",
                    message="article has no raw content archive URI",
                )
            )
            continue

        try:
            # Construct the production reader only if this batch actually needs it;
            # callers can inject a deterministic reader for tests.
            if archive_reader is None:
                archive_reader = GCSArchivedContentReader()
            clean_text = archive_reader.read_clean_text(archive_uri)
        except ArchiveReadError as e:
            run.errors.append(
                RunError(
                    url=article.url,
                    stage="archive-read",
                    message=str(e)[:200],
                )
            )
            continue
        except Exception as e:
            run.errors.append(
                RunError(
                    url=article.url,
                    stage="archive-read",
                    message=(f"archive reader failed for {archive_uri}: {type(e).__name__}: {e}")[
                        :200
                    ],
                )
            )
            continue

        extraction_snapshot = {
            "title": article.title,
            "summary": article.summary,
            "tickers": article.tickers,
            "sentiment": article.sentiment.model_dump(),
            "core_thesis": article.core_thesis,
            "categories": article.categories,
            "entities": [e.model_dump() for e in article.entities],
            "language": article.language,
        }

        try:
            result = judge.judge(
                article_url=article.url,
                clean_text=clean_text,
                extraction_json=json.dumps(extraction_snapshot, ensure_ascii=False),
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
