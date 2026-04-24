import hashlib
from datetime import UTC, datetime
from urllib.parse import urlparse, urlunparse

from app.models.article import Source


def _normalize_url(url: str) -> str:
    p = urlparse(url)
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme, p.netloc, path, "", p.query, ""))


def compute_article_id(source: Source, published_at: datetime, url: str) -> str:
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    date_str = published_at.astimezone(UTC).strftime("%Y%m%d")
    h = hashlib.md5(_normalize_url(url).encode("utf-8")).hexdigest()[:8]
    return f"{source}_{date_str}_{h}"
