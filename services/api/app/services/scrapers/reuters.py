import logging
from datetime import UTC, datetime

import feedparser

from app.http_client import UA_DESKTOP
from app.models.candidate import Candidate
from app.models.ingest import IngestPayload, RawHtml
from app.services.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

FEEDS = [
    "https://feeds.reuters.com/reuters/businessNews",
    "https://feeds.reuters.com/reuters/marketsNews",
]


class ReutersScraper(BaseScraper):
    source_name = "reuters"

    async def list_candidates(self, limit: int = 50) -> list[Candidate]:
        seen: dict[str, Candidate] = {}
        for feed_url in FEEDS:
            try:
                resp = await self._http.get(feed_url, timeout=15.0)
                resp.raise_for_status()
            except Exception:  # feed fetches must not break the cron run; log and continue
                logger.warning("Reuters feed fetch failed", extra={"feed": feed_url})
                continue
            parsed = feedparser.parse(resp.text)
            for entry in parsed.entries[:limit]:
                url = entry.link
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
        year, month, day, hour, minute, second = struct[:6]
        return datetime(year, month, day, hour, minute, second, tzinfo=UTC)

    async def fetch_one(self, candidate: Candidate) -> IngestPayload:
        resp = await self._http.get(
            candidate.url,
            timeout=15.0,
            headers={"User-Agent": UA_DESKTOP},
        )
        resp.raise_for_status()
        return IngestPayload(
            source="reuters",
            source_id=candidate.source_id,
            url=candidate.url,
            fetched_at=datetime.now(UTC),
            raw=RawHtml(kind="html", html=resp.text),
        )
