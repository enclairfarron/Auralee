import logging
import re
from datetime import UTC, datetime

import feedparser

from app.models.candidate import Candidate
from app.models.ingest import IngestPayload, RawText
from app.services.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# NOTE: Reuters discontinued public RSS (feeds.reuters.com is dead as of 2025).
# Replaced with MarketWatch — Dow Jones owned, financial focus, free RSS.
# TODO(week2): rename "reuters" -> "marketwatch" throughout (Source enum,
# scheduler job, etc.). Source label is misleading until then.
FEEDS = [
    "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "https://feeds.content.dowjones.io/public/rss/mw_marketpulse",
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
                    description=_clean_html(entry.get("summary") or entry.get("description") or ""),
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
        # Dow Jones (MarketWatch/WSJ) blocks Cloud Run egress IPs with 401.
        # We don't HTTP-fetch the article URL; instead we use the RSS-provided
        # title + description as the body. RSS descriptions are 200-500 chars
        # of summary, enough for Gemini to extract ticker/sentiment/thesis.
        body_parts = [candidate.title or "", candidate.description or ""]
        body = "\n\n".join(p for p in body_parts if p)
        return IngestPayload(
            source="reuters",
            source_id=candidate.source_id,
            url=candidate.url,
            fetched_at=datetime.now(UTC),
            raw=RawText(
                kind="text",
                title=candidate.title or "",
                body=body,
                metadata={"published_at": (candidate.published_at or datetime.now(UTC)).isoformat()},
            ),
        )


_TAG_RE = re.compile(r"<[^>]+>")


def _clean_html(text: str) -> str:
    """Strip HTML tags from RSS description (some feeds embed HTML)."""
    return _TAG_RE.sub("", text).strip()
