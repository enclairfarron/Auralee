from datetime import datetime

from pydantic import BaseModel


class Candidate(BaseModel):
    source_id: str
    url: str
    title: str | None = None
    published_at: datetime | None = None
