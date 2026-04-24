from datetime import datetime

from pydantic import BaseModel


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
