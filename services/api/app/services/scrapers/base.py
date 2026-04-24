from abc import ABC, abstractmethod

import httpx

from app.models.candidate import Candidate
from app.models.ingest import IngestPayload


class BaseScraper(ABC):
    source_name: str

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    @abstractmethod
    async def list_candidates(self, limit: int = 50) -> list[Candidate]: ...

    @abstractmethod
    async def fetch_one(self, candidate: Candidate) -> IngestPayload: ...
