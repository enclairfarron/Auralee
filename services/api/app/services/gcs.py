import logging
from datetime import UTC, datetime
from typing import Any

from google.cloud import storage  # type: ignore[attr-defined]

from app.models.article import Source

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
        blob.upload_from_string(html, content_type="text/html; charset=utf-8")
        uri = f"gs://{self._bucket_name}/{path}"
        logger.info("archived raw HTML", extra={"uri": uri, "article_id": article_id})
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
        except Exception:
            logger.exception("failed to archive raw HTML", extra={"article_id": article_id})
            return None
