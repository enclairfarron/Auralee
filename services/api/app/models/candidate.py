from datetime import datetime

from pydantic import BaseModel


class Candidate(BaseModel):
    source_id: str
    url: str
    title: str | None = None
    published_at: datetime | None = None
    # Optional RSS description / summary text. Used by sources that can't fetch
    # full article HTML (e.g. anti-bot 401) and fall back to RSS-provided text.
    description: str | None = None
