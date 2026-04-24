import hashlib
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from app.models.article import Source

_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAMS = frozenset({"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src", "mod"})


def _strip_tracking(query: str) -> str:
    if not query:
        return ""
    pairs = parse_qsl(query, keep_blank_values=True)
    keep = [
        (k, v)
        for k, v in pairs
        if not any(k.startswith(p) for p in _TRACKING_PARAM_PREFIXES)
        and k.lower() not in _TRACKING_PARAMS
    ]
    return urlencode(keep)


def _normalize_url(url: str) -> str:
    p = urlparse(url)
    netloc = p.netloc.lower()  # I2: hosts are case-insensitive (RFC 3986)
    path = p.path.rstrip("/") or "/"
    query = _strip_tracking(p.query)
    return urlunparse((p.scheme, netloc, path, "", query, ""))


def compute_article_id(source: Source, published_at: datetime, url: str) -> str:
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    date_str = published_at.astimezone(UTC).strftime("%Y%m%d")
    h = hashlib.md5(_normalize_url(url).encode("utf-8")).hexdigest()[:8]
    return f"{source}_{date_str}_{h}"
