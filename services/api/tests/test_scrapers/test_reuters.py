from importlib.resources import files

import httpx
import pytest
from pytest_httpx import HTTPXMock

from app.services.scrapers.reuters import FEEDS, ReutersScraper


@pytest.mark.asyncio
async def test_list_candidates_parses_rss_and_dedupes(httpx_mock: HTTPXMock) -> None:
    feed = files("tests.data").joinpath("reuters_feed.xml").read_text()
    for url in FEEDS:
        httpx_mock.add_response(url=url, text=feed)

    async with httpx.AsyncClient() as client:
        scraper = ReutersScraper(http=client)
        candidates = await scraper.list_candidates(limit=10)

    # 2 items per feed x N feeds, but dedupe by URL -> 2 unique
    assert len(candidates) == 2
    titles = {c.title for c in candidates}
    assert "Apple beats earnings" in titles


@pytest.mark.asyncio
async def test_fetch_one_returns_text_payload_from_rss_description() -> None:
    """fetch_one no longer HTTP-fetches the article URL — Dow Jones (MW/WSJ)
    blocks Cloud Run egress with 401. Instead it packages the title + RSS
    description (captured during list_candidates) into a RawText payload."""
    async with httpx.AsyncClient() as client:
        scraper = ReutersScraper(http=client)
        from datetime import UTC, datetime

        from app.models.candidate import Candidate

        c = Candidate(
            source_id="1",
            url="https://www.marketwatch.com/story/apple-q2",
            title="Apple beats Q2",
            published_at=datetime(2026, 4, 24, tzinfo=UTC),
            description="Apple Inc. reported quarterly earnings exceeding analyst expectations, driven by strong iPhone sales.",
        )
        payload = await scraper.fetch_one(c)

    assert payload.source == "reuters"
    assert payload.published_at == c.published_at
    assert payload.raw.kind == "text"
    assert "Apple beats Q2" in payload.raw.body
    assert "iPhone sales" in payload.raw.body


@pytest.mark.asyncio
async def test_list_candidates_captures_description_from_rss(httpx_mock: HTTPXMock) -> None:
    """list_candidates should populate Candidate.description from RSS summary."""
    feed = files("tests.data").joinpath("reuters_feed.xml").read_text()
    for url in FEEDS:
        httpx_mock.add_response(url=url, text=feed)

    async with httpx.AsyncClient() as client:
        scraper = ReutersScraper(http=client)
        candidates = await scraper.list_candidates(limit=10)

    # The fixture has <description> on each <item>; assert it's captured.
    assert all(c.description is not None for c in candidates)
