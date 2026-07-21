import asyncio
import logging
from datetime import UTC, datetime

import httpx

from app.models.candidate import Candidate
from app.models.ingest import IngestPayload, RawHtml, RawText
from app.services.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

_TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{id}.json"


class HNScraper(BaseScraper):
    source_name = "hn"

    async def list_candidates(self, limit: int = 30) -> list[Candidate]:
        ids_response = await self._http.get(_TOP_STORIES_URL)
        ids_response.raise_for_status()
        ids: list[int] = ids_response.json()[:limit]

        items = await asyncio.gather(*[self._fetch_item(i) for i in ids], return_exceptions=False)

        candidates: list[Candidate] = []
        for item in items:
            if not item or item.get("type") != "story":
                continue
            url = item.get("url") or f"https://news.ycombinator.com/item?id={item['id']}"
            candidates.append(
                Candidate(
                    source_id=str(item["id"]),
                    url=url,
                    title=item.get("title"),
                    published_at=datetime.fromtimestamp(item["time"], tz=UTC),
                )
            )
        return candidates

    async def _fetch_item(self, item_id: int) -> dict | None:  # type: ignore[type-arg]
        try:
            r = await self._http.get(_ITEM_URL.format(id=item_id), timeout=10.0)
            r.raise_for_status()
            return r.json()  # type: ignore[no-any-return]
        except (httpx.HTTPError, ValueError):
            logger.warning("HN item fetch failed", extra={"item_id": item_id})
            return None

    async def fetch_one(self, candidate: Candidate) -> IngestPayload:
        try:
            r = await self._http.get(candidate.url, timeout=10.0)
            r.raise_for_status()
            return IngestPayload(
                source="hn",
                source_id=candidate.source_id,
                url=candidate.url,
                published_at=candidate.published_at,
                fetched_at=datetime.now(UTC),
                raw=RawHtml(kind="html", html=r.text),
            )
        except httpx.HTTPError:
            logger.info(
                "HN external URL fetch failed; falling back to title-only",
                extra={"url": candidate.url},
            )
            return IngestPayload(
                source="hn",
                source_id=candidate.source_id,
                url=candidate.url,
                published_at=candidate.published_at,
                fetched_at=datetime.now(UTC),
                raw=RawText(
                    kind="text",
                    title=candidate.title or "",
                    body=candidate.title or "",
                    metadata=(
                        {"published_at": candidate.published_at.isoformat()}
                        if candidate.published_at
                        else {}
                    ),
                ),
            )
