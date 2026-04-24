from importlib.resources import files

import httpx
import pytest
from pytest_httpx import HTTPXMock

from app.services.scrapers.wsj import (
    RSS_FEEDS,
    WSJCookieExpiredError,
    WSJScraper,
)


@pytest.mark.asyncio
async def test_list_candidates_filters_to_articles_only(httpx_mock: HTTPXMock) -> None:
    feed = files("tests.data").joinpath("wsj_feed.xml").read_text()
    for url in RSS_FEEDS:
        httpx_mock.add_response(url=url, text=feed)

    async with httpx.AsyncClient() as client:
        scraper = WSJScraper(http=client, cookie="cookie=value")
        candidates = await scraper.list_candidates(limit=10)

    assert len(candidates) == 1  # video link filtered
    assert "wsj.com/articles/" in candidates[0].url


@pytest.mark.asyncio
async def test_fetch_one_includes_cookie_and_returns_html(httpx_mock: HTTPXMock) -> None:
    body = "Long article body. " * 800  # > 5000 chars
    httpx_mock.add_response(
        url="https://www.wsj.com/articles/apple-q2-12345",
        text=f"<html><body><article>{body}</article></body></html>",
    )
    async with httpx.AsyncClient() as client:
        scraper = WSJScraper(http=client, cookie="auth=secret")
        from datetime import UTC, datetime

        from app.models.candidate import Candidate

        c = Candidate(
            source_id="WP-1",
            url="https://www.wsj.com/articles/apple-q2-12345",
            title="Apple",
            published_at=datetime(2026, 4, 24, tzinfo=UTC),
        )
        payload = await scraper.fetch_one(c)

    assert payload.source == "wsj"
    assert payload.raw.kind == "html"
    sent_request = httpx_mock.get_request(url="https://www.wsj.com/articles/apple-q2-12345")
    assert sent_request is not None
    assert sent_request.headers.get("Cookie") == "auth=secret"


@pytest.mark.asyncio
async def test_paywall_signature_raises_cookie_expired(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://www.wsj.com/articles/blocked",
        text="<html><body>Sign In to Continue Reading</body></html>",
    )
    async with httpx.AsyncClient() as client:
        scraper = WSJScraper(http=client, cookie="x")
        from datetime import UTC, datetime

        from app.models.candidate import Candidate

        c = Candidate(
            source_id="x",
            url="https://www.wsj.com/articles/blocked",
            title="t",
            published_at=datetime(2026, 4, 24, tzinfo=UTC),
        )
        with pytest.raises(WSJCookieExpiredError):
            await scraper.fetch_one(c)


@pytest.mark.asyncio
async def test_short_response_also_raises_cookie_expired(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://www.wsj.com/articles/short",
        text="<html><body>tiny</body></html>",
    )
    async with httpx.AsyncClient() as client:
        scraper = WSJScraper(http=client, cookie="x")
        from datetime import UTC, datetime

        from app.models.candidate import Candidate

        c = Candidate(
            source_id="x",
            url="https://www.wsj.com/articles/short",
            title="t",
            published_at=datetime(2026, 4, 24, tzinfo=UTC),
        )
        with pytest.raises(WSJCookieExpiredError):
            await scraper.fetch_one(c)
