from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.candidate import Candidate
from app.models.ingest import IngestMeta, IngestPayload, IngestResponse, RawText
from app.services.scrape_runner import run_scrape


def _candidate(i: int) -> Candidate:
    return Candidate(
        source_id=str(i),
        url=f"https://x/{i}",
        title=f"T{i}",
        published_at=datetime(2026, 4, 24, tzinfo=UTC),
    )


def _ingested_resp(article_id: str, cost: float = 0.0001) -> IngestResponse:
    return IngestResponse(
        article_id=article_id,
        status="ingested",
        meta=IngestMeta(
            tokens_in=10,
            tokens_out=5,
            cost_usd=cost,
            latency_ms=100,
            prompt_version="v1",
        ),
    )


@pytest.mark.asyncio
async def test_run_scrape_aggregates_counts_and_cost() -> None:
    scraper = MagicMock()
    scraper.source_name = "hn"
    scraper.list_candidates = AsyncMock(return_value=[_candidate(1), _candidate(2)])
    scraper.fetch_one = AsyncMock(
        side_effect=lambda c: IngestPayload(
            source="hn",
            source_id=c.source_id,
            url=c.url,
            fetched_at=datetime.now(UTC),
            raw=RawText(kind="text", title=c.title or "", body=c.title or ""),
        )
    )

    ingest = MagicMock()
    ingest.process = MagicMock(
        side_effect=[
            _ingested_resp("hn_1", 0.0001),
            _ingested_resp("hn_2", 0.0002),
        ]
    )

    repo = MagicMock()
    repo.save_run = MagicMock(return_value="run-id")

    summary = await run_scrape(scraper=scraper, ingest=ingest, repo=repo)

    assert summary["ingested"] == 2
    assert summary["attempted"] == 2
    assert summary["cost_usd"] == pytest.approx(0.0003)
    saved_run = repo.save_run.call_args[0][0]
    assert saved_run.kind == "scrape"
    assert saved_run.source == "hn"


@pytest.mark.asyncio
async def test_run_scrape_records_errors_and_continues() -> None:
    scraper = MagicMock()
    scraper.source_name = "wsj"
    scraper.list_candidates = AsyncMock(return_value=[_candidate(1), _candidate(2)])

    async def fetch(c: Candidate) -> IngestPayload:
        if c.source_id == "1":
            raise RuntimeError("boom")
        return IngestPayload(
            source="wsj",
            source_id=c.source_id,
            url=c.url,
            fetched_at=datetime.now(UTC),
            raw=RawText(kind="text", title=c.title or "", body=c.title or ""),
        )

    scraper.fetch_one = AsyncMock(side_effect=fetch)
    ingest = MagicMock()
    ingest.process = MagicMock(return_value=_ingested_resp("wsj_2"))
    repo = MagicMock()

    summary = await run_scrape(scraper=scraper, ingest=ingest, repo=repo)

    assert summary["ingested"] == 1
    assert summary["errors"] == 1
    saved_run = repo.save_run.call_args[0][0]
    assert saved_run.status == "partial"


@pytest.mark.asyncio
async def test_run_scrape_skips_when_already_ingested() -> None:
    scraper = MagicMock()
    scraper.source_name = "hn"
    scraper.list_candidates = AsyncMock(return_value=[_candidate(1)])
    scraper.fetch_one = AsyncMock()
    ingest = MagicMock()
    ingest.process = MagicMock(return_value=IngestResponse(article_id="hn_1", status="duplicate"))
    repo = MagicMock()

    summary = await run_scrape(scraper=scraper, ingest=ingest, repo=repo)
    assert summary["skipped_dup"] == 1
    assert summary["ingested"] == 0
