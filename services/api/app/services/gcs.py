import json
import logging
from datetime import UTC, datetime
from typing import Any

from google.api_core.exceptions import PreconditionFailed
from google.cloud import storage  # type: ignore[attr-defined]

from app.models.article import Source
from app.models.ingest import RawText

logger = logging.getLogger(__name__)


class RawHtmlArchiver:
    def __init__(self, bucket_name: str, _client: Any | None = None) -> None:
        self._bucket_name = bucket_name
        self._client = _client or storage.Client()

    def upload(
        self,
        article_id: str,
        source: Source,
        published_at: datetime,
        html: str,
    ) -> str:
        date_str = published_at.astimezone(UTC).strftime("%Y-%m-%d")
        path = f"{source}/{date_str}/{article_id}.html"
        blob = self._client.bucket(self._bucket_name).blob(path)
        blob.upload_from_string(
            html,
            content_type="text/html; charset=utf-8",
            if_generation_match=0,
        )
        uri = f"gs://{self._bucket_name}/{path}"
        logger.info("archived raw HTML", extra={"uri": uri, "article_id": article_id})
        return uri

    def upload_text(
        self,
        article_id: str,
        source: Source,
        published_at: datetime,
        raw_text: RawText,
    ) -> str:
        """Archive RawText as canonical UTF-8 JSON for later evaluation/replay."""
        date_str = published_at.astimezone(UTC).strftime("%Y-%m-%d")
        path = f"{source}/{date_str}/{article_id}.json"
        content = json.dumps(
            raw_text.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        blob = self._client.bucket(self._bucket_name).blob(path)
        blob.upload_from_string(
            content,
            content_type="application/json; charset=utf-8",
            if_generation_match=0,
        )
        uri = f"gs://{self._bucket_name}/{path}"
        logger.info("archived raw text", extra={"uri": uri, "article_id": article_id})
        return uri

    def upload_safe(
        self,
        article_id: str,
        source: Source,
        published_at: datetime,
        html: str,
    ) -> str | None:
        """Fire-and-forget variant: log and swallow exceptions."""
        try:
            return self.upload(article_id, source, published_at, html)
        except PreconditionFailed:
            # The deterministic object already exists. Keep the first-seen bytes
            # immutable and return the stable URI (notably during /admin/reingest).
            date_str = published_at.astimezone(UTC).strftime("%Y-%m-%d")
            return f"gs://{self._bucket_name}/{source}/{date_str}/{article_id}.html"
        except Exception:
            logger.exception("failed to archive raw HTML", extra={"article_id": article_id})
            return None

    def upload_text_safe(
        self,
        article_id: str,
        source: Source,
        published_at: datetime,
        raw_text: RawText,
    ) -> str | None:
        """Best-effort RawText archive that never overwrites first-seen evidence."""
        try:
            return self.upload_text(article_id, source, published_at, raw_text)
        except PreconditionFailed:
            date_str = published_at.astimezone(UTC).strftime("%Y-%m-%d")
            return f"gs://{self._bucket_name}/{source}/{date_str}/{article_id}.json"
        except Exception:
            logger.exception("failed to archive raw text", extra={"article_id": article_id})
            return None
