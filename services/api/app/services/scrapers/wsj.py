import logging
from datetime import UTC, datetime

import feedparser
import httpx

from app.http_client import UA_SAFARI_MAC
from app.models.candidate import Candidate
from app.models.ingest import IngestPayload, RawHtml
from app.services.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

RSS_FEEDS = [
    "https://feeds.a.dj.com/rss/RSSWSJD.xml",
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    "https://feeds.a.dj.com/rss/RSSWSJBuyside.xml",
]

_PAYWALL_MARKERS = (
    "Sign In to Continue Reading",
    "Subscribe to continue reading",
)
_MIN_HTML_LEN = 5000


class WSJCookieExpiredError(RuntimeError):
    pass


class WSJScraper(BaseScraper):
    source_name = "wsj"

    def __init__(self, http: httpx.AsyncClient, cookie: str) -> None:
        super().__init__(http)
        self._cookie = cookie

    async def list_candidates(self, limit: int = 50) -> list[Candidate]:
        seen: dict[str, Candidate] = {}
        for feed_url in RSS_FEEDS:
            try:
                resp = await self._http.get(feed_url, timeout=15.0)
                resp.raise_for_status()
            except Exception:  # broad on purpose; feed failures must not break cron
                logger.warning("WSJ feed fetch failed", extra={"feed": feed_url})
                continue
            parsed = feedparser.parse(resp.text)
            for entry in parsed.entries[:limit]:
                url = entry.link
                if "wsj.com/articles/" not in url:
                    continue
                if url in seen:
                    continue
                published = self._parse_pubdate(entry)
                seen[url] = Candidate(
                    source_id=entry.get("id") or url,
                    url=url,
                    title=entry.get("title"),
                    published_at=published,
                )
        return list(seen.values())

    @staticmethod
    def _parse_pubdate(entry: dict) -> datetime | None:  # type: ignore[type-arg]
        struct = entry.get("published_parsed") or entry.get("updated_parsed")
        if not struct:
            return None
        y, m, d, h, mi, s = struct[:6]
        return datetime(y, m, d, h, mi, s, tzinfo=UTC)

    async def fetch_one(self, candidate: Candidate) -> IngestPayload:
        # Full browser-equivalent header set. Without Sec-Fetch-* + Accept-Encoding
        # WSJ returns 401 even with a valid logged-in cookie. With these headers
        # WSJ accepts the request and follows redirects from /articles/X to its
        # new /category/sub/X URL structure (httpx follow_redirects handles it).
        resp = await self._http.get(
            candidate.url,
            timeout=20.0,
            headers={
                "Cookie": self._cookie,
                "User-Agent": UA_SAFARI_MAC,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
                "Referer": "https://www.wsj.com/",
            },
        )
        resp.raise_for_status()
        html = resp.text
        if any(m in html for m in _PAYWALL_MARKERS) or len(html) < _MIN_HTML_LEN:
            raise WSJCookieExpiredError(f"paywall or short response for {candidate.url}")
        return IngestPayload(
            source="wsj",
            source_id=candidate.source_id,
            url=candidate.url,
            fetched_at=datetime.now(UTC),
            raw=RawHtml(kind="html", html=html),
        )
