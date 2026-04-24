from datetime import date as _date
from datetime import datetime

from pydantic import BaseModel, field_validator


class Price(BaseModel):
    ticker: str
    name: str | None = None
    exchange: str | None = None
    currency: str = "USD"
    first_seen_at: datetime
    last_refreshed_at: datetime | None = None
    is_active: bool = True


class DailyOHLC(BaseModel):
    date: str  # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: int
    adj_close: float
    fetched_at: datetime
    source: str = "yfinance"

    @field_validator("date")
    @classmethod
    def _validate_date(cls, v: str) -> str:
        try:
            _date.fromisoformat(v)
        except ValueError as e:
            raise ValueError(f"date must be YYYY-MM-DD, got {v!r}") from e
        return v
