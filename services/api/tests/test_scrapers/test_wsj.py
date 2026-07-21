from datetime import UTC, datetime
from importlib.resources import files
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pytest_httpx import HTTPXMock

from app.models.candidate import Candidate
from app.services.scrapers.wsj import (
    RSS_FEEDS,
    WSJCookieExpiredError,
    WSJScraper,
)


@pytest.mark.asyncio
async def test_list_candidates_filters_to_articles_only(httpx_mock: HTTPXMock) -> None:
    """RSS feed parsing still uses httpx (works fine for RSS)."""
    feed = files("tests.data").joinpath("wsj_feed.xml").read_text()
    for url in RSS_FEEDS:
        httpx_mock.add_response(url=url, text=feed)

    async with httpx.AsyncClient() as client:
        scraper = WSJScraper(http=client, cookie="cookie=value")
        candidates = await scraper.list_candidates(limit=10)

    assert len(candidates) == 1  # video link filtered
    assert "wsj.com/articles/" in candidates[0].url


def _make_candidate(url: str = "https://www.wsj.com/articles/apple-q2-12345") -> Candidate:
    return Candidate(
        source_id="WP-1",
        url=url,
        title="Apple",
        published_at=datetime(2026, 4, 24, tzinfo=UTC),
    )


def _make_curl_response(status_code: int, text: str) -> MagicMock:
    """Build a fake curl_cffi Response."""
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    r.content = text.encode()
    return r


@pytest.mark.asyncio
async def test_fetch_one_uses_curl_cffi_with_safari_impersonate_and_cookie() -> None:
    """fetch_one uses curl_cffi.AsyncSession with impersonate=safari184. Mock
    AsyncSession entirely; verify it was called with the right impersonate +
    Cookie header, and returns a RawHtml IngestPayload on 200."""
    body = "Long article body. " * 800  # > 5000 chars
    full_html = f"<html><body><article>{body}</article></body></html>"

    fake_session = MagicMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)
    fake_session.get = AsyncMock(return_value=_make_curl_response(200, full_html))

    with patch("app.services.scrapers.wsj.AsyncSession", return_value=fake_session) as ms:
        async with httpx.AsyncClient() as client:
            scraper = WSJScraper(http=client, cookie="auth=secret")
            payload = await scraper.fetch_one(_make_candidate())

    # AsyncSession constructed with safari impersonation
    ms.assert_called_once()
    assert ms.call_args.kwargs.get("impersonate") == "safari184"
    # Get call sent the cookie via headers
    fake_session.get.assert_awaited_once()
    sent_headers = fake_session.get.call_args.kwargs["headers"]
    assert sent_headers["Cookie"] == "auth=secret"
    assert sent_headers["Referer"] == "https://www.wsj.com/"
    # Returned payload shape
    assert payload.source == "wsj"
    assert payload.published_at == _make_candidate().published_at
    assert payload.raw.kind == "html"


@pytest.mark.asyncio
async def test_fetch_one_raises_on_non_200_status() -> None:
    fake_session = MagicMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)
    fake_session.get = AsyncMock(return_value=_make_curl_response(401, "denied"))

    with patch("app.services.scrapers.wsj.AsyncSession", return_value=fake_session):
        async with httpx.AsyncClient() as client:
            scraper = WSJScraper(http=client, cookie="x")
            with pytest.raises(WSJCookieExpiredError, match="returned 401"):
                await scraper.fetch_one(_make_candidate())


@pytest.mark.asyncio
async def test_paywall_signature_raises_cookie_expired() -> None:
    fake_session = MagicMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)
    fake_session.get = AsyncMock(
        return_value=_make_curl_response(
            200, "<html><body>Sign In to Continue Reading</body></html>"
        )
    )

    with patch("app.services.scrapers.wsj.AsyncSession", return_value=fake_session):
        async with httpx.AsyncClient() as client:
            scraper = WSJScraper(http=client, cookie="x")
            with pytest.raises(WSJCookieExpiredError, match="paywall or short"):
                await scraper.fetch_one(_make_candidate())


@pytest.mark.asyncio
async def test_short_response_also_raises_cookie_expired() -> None:
    fake_session = MagicMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)
    fake_session.get = AsyncMock(
        return_value=_make_curl_response(200, "<html><body>tiny</body></html>")
    )

    with patch("app.services.scrapers.wsj.AsyncSession", return_value=fake_session):
        async with httpx.AsyncClient() as client:
            scraper = WSJScraper(http=client, cookie="x")
            with pytest.raises(WSJCookieExpiredError, match="paywall or short"):
                await scraper.fetch_one(_make_candidate())
