from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RunKind = Literal["scrape", "refresh-prices", "aggregate-metrics", "eval-judge"]
RunStatus = Literal["success", "partial", "failure", "noop"]


class RunError(BaseModel):
    url: str | None = None
    ticker: str | None = None
    stage: str
    message: str


class Run(BaseModel):
    id: str
    kind: RunKind
    source: str | None = None  # for scrape only
    started_at: datetime
    finished_at: datetime | None = None
    status: RunStatus = "success"
    articles_attempted: int = 0
    articles_ingested: int = 0
    articles_skipped_dup: int = 0
    articles_skipped_short: int = 0
    # Older run documents predate per-outcome accounting. A zero count is only
    # authoritative when this flag is true.
    outcome_counts_complete: bool = False
    refreshed: int = 0
    errors: list[RunError] = Field(default_factory=list)
    cost_usd: float = 0.0
