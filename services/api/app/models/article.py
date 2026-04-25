from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Source = Literal["hn", "reuters", "wsj"]
SentimentLabel = Literal["bullish", "bearish", "neutral"]
EntityType = Literal["company", "person", "location", "product"]


class Sentiment(BaseModel):
    score: float = Field(ge=-1.0, le=1.0)
    label: SentimentLabel


class Entity(BaseModel):
    type: EntityType
    name: str
    ticker: str | None = None


class GeminiMeta(BaseModel):
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    prompt_version: str


class SanityCheck(BaseModel):
    ticker_precision_pass: bool
    checked_at: datetime
    flags: list[str] = Field(default_factory=list)


class EvalScore(BaseModel):
    score: float = Field(ge=0.0, le=10.0)
    judge_model: str
    judged_at: datetime
    issues: list[str] = Field(default_factory=list)
    reasoning: str


class Extraction(BaseModel):
    """Schema fed to Gemini as response_schema.

    Note: ConfigDict(extra="forbid") was REMOVED — it generates
    additionalProperties:false in the JSON schema, which the Gemini API rejects
    with INVALID_ARGUMENT ('Unknown name "additional_properties"'). Without it
    Gemini may technically include extra fields, but in practice with
    response_schema enforcement that doesn't happen.
    """

    title: str
    summary: str = Field(description="2-3 sentences in the SAME language as the article")
    tickers: list[str] = Field(
        default_factory=list,
        description="US-listed tickers, uppercase, e.g. ['AAPL']",
    )
    sentiment: Sentiment
    core_thesis: str = Field(description="Article's central argument, 1 sentence")
    categories: list[str] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    language: str = Field(description="ISO 639-1 code")


class Article(BaseModel):
    """Firestore document for `articles/{id}`."""

    id: str
    source: Source
    source_id: str
    url: str
    title: str
    author: str | None = None
    published_at: datetime
    fetched_at: datetime
    processed_at: datetime
    language: str

    raw_html_gcs_uri: str | None = None
    clean_text_chars: int = 0

    summary: str
    tickers: list[str] = Field(default_factory=list)
    sentiment: Sentiment
    core_thesis: str
    categories: list[str] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)

    gemini_meta: GeminiMeta

    sanity_check: SanityCheck | None = None
    eval_score: EvalScore | None = None

    # Week 2 reservations
    embedding: list[float] | None = None
    embedding_model: str | None = None
    embedded_at: datetime | None = None
