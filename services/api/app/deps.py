from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings
from app.services.firestore_repo import FirestoreRepo
from app.services.gcs import RawHtmlArchiver
from app.services.gemini import GeminiExtractor
from app.services.ingest_service import IngestService
from app.services.secrets import SecretClient


def require_admin_token(
    x_admin_token: Annotated[str | None, Header()] = None,
    settings: Annotated[Settings, Depends(get_settings)] = ...,  # type: ignore[assignment]
) -> None:
    if not settings.admin_token:
        raise HTTPException(status_code=503, detail="ADMIN_TOKEN not configured")
    if not x_admin_token or x_admin_token != settings.admin_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")


@lru_cache(maxsize=1)
def get_repo() -> FirestoreRepo:
    return FirestoreRepo()


@lru_cache(maxsize=1)
def get_archiver() -> RawHtmlArchiver:
    return RawHtmlArchiver(bucket_name=get_settings().raw_bucket)


@lru_cache(maxsize=1)
def get_secrets() -> SecretClient:
    return SecretClient(project_id=get_settings().gcp_project)


@lru_cache(maxsize=1)
def get_extractor() -> GeminiExtractor:
    s = get_settings()
    return GeminiExtractor(api_key=s.gemini_api_key, model=s.extraction_model)


def get_ingest_service(
    repo: Annotated[FirestoreRepo, Depends(get_repo)],
    extractor: Annotated[GeminiExtractor, Depends(get_extractor)],
    archiver: Annotated[RawHtmlArchiver, Depends(get_archiver)],
) -> IngestService:
    return IngestService(repo=repo, extractor=extractor, archiver=archiver)
