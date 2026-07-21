from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from google.cloud import storage as gcs_storage  # type: ignore[attr-defined]
from pydantic import ValidationError

from app.deps import (
    get_archiver,
    get_extractor,
    get_repo,
    get_secrets,
    require_admin_token,
)
from app.models.article import Article
from app.models.ingest import IngestPayload, IngestResponse, RawHtml, RawText
from app.services.firestore_repo import FirestoreRepo
from app.services.gcs import RawHtmlArchiver
from app.services.gemini import GeminiExtractor
from app.services.ingest_service import IngestService
from app.services.secrets import SecretClient

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


@router.get("/articles", response_model=list[Article])
async def list_articles(
    repo: Annotated[FirestoreRepo, Depends(get_repo)],
    source: Annotated[Literal["hn", "reuters", "wsj"] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[Article]:
    return repo.list_recent_articles(source=source, limit=limit)


@router.get("/articles/{article_id}", response_model=Article)
async def get_article(
    article_id: Annotated[str, Path()],
    repo: Annotated[FirestoreRepo, Depends(get_repo)],
) -> Article:
    article = repo.get_article(article_id)
    if not article:
        raise HTTPException(404, detail="article not found")
    return article


@router.get("/runs")
async def list_runs(
    repo: Annotated[FirestoreRepo, Depends(get_repo)],
    kind: Annotated[str | None, Query()] = None,
    source: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[dict]:  # type: ignore[type-arg]
    runs = repo.list_runs(kind=kind, source=source, limit=limit)
    return [r.model_dump(mode="json") for r in runs]


@router.get("/runs/{run_id}")
async def get_run(
    run_id: Annotated[str, Path()],
    repo: Annotated[FirestoreRepo, Depends(get_repo)],
) -> dict:  # type: ignore[type-arg]
    r = repo.get_run(run_id)
    if not r:
        raise HTTPException(404, detail="run not found")
    return r.model_dump(mode="json")


@router.get("/stats")
async def get_stats(
    repo: Annotated[FirestoreRepo, Depends(get_repo)],
    date: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
) -> dict:  # type: ignore[type-arg]
    target = (
        datetime.strptime(date, "%Y-%m-%d").date()
        if date
        else (datetime.now(UTC).date() - timedelta(days=1))
    )
    metrics = repo.get_metrics(target.strftime("%Y%m%d"))
    if not metrics:
        raise HTTPException(404, detail=f"no metrics for {target.isoformat()}")
    return metrics


@router.get("/stats/summary")
async def get_stats_summary(
    repo: Annotated[FirestoreRepo, Depends(get_repo)],
    days: Annotated[int, Query(ge=1, le=30)] = 7,
) -> dict:  # type: ignore[type-arg]
    today = datetime.now(UTC).date()
    rows: list[dict] = []  # type: ignore[type-arg]
    for offset in range(1, days + 1):
        d = today - timedelta(days=offset)
        m = repo.get_metrics(d.strftime("%Y%m%d"))
        if m:
            rows.append(m)
    return {"days": len(rows), "rows": rows}


@router.get("/healthz-detail")
async def healthz_detail(
    repo: Annotated[FirestoreRepo, Depends(get_repo)],
    secrets: Annotated[SecretClient, Depends(get_secrets)],
    extractor: Annotated[GeminiExtractor, Depends(get_extractor)],
) -> dict[str, bool | str]:
    out: dict[str, bool | str] = {
        "firestore": False,
        "secrets_wsj_cookie": False,
        "vertex_ai": False,
        "vertex_model": extractor.model,
    }
    try:
        repo.list_all_tickers()
        out["firestore"] = True
    except Exception as e:
        out["firestore_error"] = str(e)[:200]
    try:
        v = secrets.get("WSJ_COOKIE")
        out["secrets_wsj_cookie"] = bool(v)
    except Exception as e:
        out["secrets_wsj_cookie_error"] = str(e)[:200]
    try:
        extractor.check_health()
        out["vertex_ai"] = True
    except Exception as e:
        out["vertex_ai_error"] = str(e)[:200]
    return out


@router.post("/reingest/{article_id}", response_model=IngestResponse)
async def reingest_article(
    article_id: Annotated[str, Path()],
    repo: Annotated[FirestoreRepo, Depends(get_repo)],
    extractor: Annotated[GeminiExtractor, Depends(get_extractor)],
    archiver: Annotated[RawHtmlArchiver, Depends(get_archiver)],
) -> IngestResponse:
    article = repo.get_article(article_id)
    if not article:
        raise HTTPException(404, detail="article not found")
    raw_content_gcs_uri = article.raw_content_gcs_uri or article.raw_html_gcs_uri
    if not raw_content_gcs_uri:
        raise HTTPException(409, detail="article has no archived content to re-extract from")

    # Read the first-seen raw content from GCS (use a fresh client; small infra).
    bucket_name, _, blob_path = raw_content_gcs_uri.removeprefix("gs://").partition("/")
    archived_content = gcs_storage.Client().bucket(bucket_name).blob(blob_path).download_as_text()
    raw: RawHtml | RawText
    if blob_path.endswith(".json"):
        try:
            raw = RawText.model_validate_json(archived_content)
        except ValidationError as exc:
            raise HTTPException(409, detail="archived text content is invalid") from exc
    else:
        # Legacy and current HTML archives both use the .html suffix.
        raw = RawHtml(kind="html", html=archived_content)

    payload = IngestPayload(
        source=article.source,
        source_id=article.source_id,
        url=article.url,
        published_at=article.published_at,
        fetched_at=article.fetched_at,
        raw=raw,
    )
    svc = IngestService(repo=repo, extractor=extractor, archiver=archiver)
    # Keep the existing Firestore document until extraction succeeds. process()
    # then overwrites the same deterministic ID, so a Vertex/cleaning failure is non-destructive.
    return svc.process(
        payload,
        allow_existing=True,
        existing_article_id=article_id,
        existing_archive_uri=raw_content_gcs_uri,
    )
