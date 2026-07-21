import httpx
import pytest
from pytest_httpx import HTTPXMock

from app.services.scrapers.hn import HNScraper


@pytest.mark.asyncio
async def test_list_candidates_returns_top_stories(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://hacker-news.firebaseio.com/v0/topstories.json",
        json=[1, 2, 3],
    )
    httpx_mock.add_response(
        url="https://hacker-news.firebaseio.com/v0/item/1.json",
        json={"id": 1, "type": "story", "title": "T1", "url": "https://x/1", "time": 1714000000},
    )
    httpx_mock.add_response(
        url="https://hacker-news.firebaseio.com/v0/item/2.json",
        json={"id": 2, "type": "story", "title": "T2", "url": "https://x/2", "time": 1714000100},
    )
    httpx_mock.add_response(
        url="https://hacker-news.firebaseio.com/v0/item/3.json",
        json={"id": 3, "type": "comment", "time": 1714000200},  # filtered out
    )

    async with httpx.AsyncClient() as client:
        scraper = HNScraper(http=client)
        candidates = await scraper.list_candidates(limit=3)

    assert len(candidates) == 2  # comment filtered
    assert candidates[0].source_id == "1"
    assert candidates[0].title == "T1"
    assert str(candidates[0].url) == "https://x/1"


@pytest.mark.asyncio
async def test_fetch_one_returns_html_payload_when_url_reachable(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://example.com/article",
        text="<html><body><p>Some article body.</p></body></html>",
    )

    async with httpx.AsyncClient() as client:
        scraper = HNScraper(http=client)
        from datetime import UTC, datetime

        from app.models.candidate import Candidate

        c = Candidate(
            source_id="42",
            url="https://example.com/article",
            title="t",
            published_at=datetime(2026, 4, 24, tzinfo=UTC),
        )
        payload = await scraper.fetch_one(c)

    assert payload.source == "hn"
    assert payload.url == "https://example.com/article"
    assert payload.published_at == c.published_at
    assert payload.raw.kind == "html"


@pytest.mark.asyncio
async def test_fetch_one_falls_back_to_text_on_fetch_failure(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_exception(httpx.ConnectError("boom"), url="https://broken.example/")

    async with httpx.AsyncClient() as client:
        scraper = HNScraper(http=client)
        from datetime import UTC, datetime

        from app.models.candidate import Candidate

        c = Candidate(
            source_id="99",
            url="https://broken.example/",
            title="A title",
            published_at=datetime(2026, 4, 24, tzinfo=UTC),
        )
        payload = await scraper.fetch_one(c)

    assert payload.raw.kind == "text"
    assert payload.raw.title == "A title"
    assert payload.published_at == c.published_at
