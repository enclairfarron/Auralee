from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, Field

from app.models.article import Extraction, Source

IngestStatus = Literal["ingested", "duplicate", "skipped_short"]


class RawHtml(BaseModel):
    kind: Literal["html"] = "html"
    html: str
    encoding: str = "utf-8"


class RawText(BaseModel):
    kind: Literal["text"] = "text"
    title: str
    body: str
    metadata: dict[str, Any] = Field(default_factory=dict)


Raw = Annotated[RawHtml | RawText, Field(discriminator="kind")]


class IngestPayload(BaseModel):
    source: Source
    source_id: str
    url: str
    published_at: datetime | None = None
    fetched_at: datetime
    raw: Raw


class IngestMeta(BaseModel):
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    prompt_version: str
    raw_content_gcs_uri: str | None = Field(
        default=None,
        validation_alias=AliasChoices("raw_content_gcs_uri", "raw_html_gcs_uri"),
    )
    # Legacy HTML-specific field. New consumers should use raw_content_gcs_uri.
    raw_html_gcs_uri: str | None = None


class IngestResponse(BaseModel):
    article_id: str
    status: IngestStatus
    extracted: Extraction | None = None  # null when status=duplicate or skipped_short
    meta: IngestMeta | None = None
