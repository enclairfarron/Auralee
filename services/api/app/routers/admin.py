from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from google.cloud import storage as gcs_storage  # type: ignore[attr-defined]

from app.deps import (
    get_archiver,
    get_extractor,
    get_repo,
    get_secrets,
    require_admin_token,
)
from app.models.article import Article
from app.models.ingest import IngestPayload, IngestResponse, RawHtml
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
) -> dict[str, bool | str]:
    out: dict[str, bool | str] = {
        "firestore": False,
        "secrets_wsj_cookie": False,
        "secrets_gemini_key": False,
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
        v = secrets.get("GEMINI_API_KEY")
        out["secrets_gemini_key"] = bool(v)
    except Exception as e:
        out["secrets_gemini_key_error"] = str(e)[:200]
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
    if not article.raw_html_gcs_uri:
        raise HTTPException(409, detail="article has no archived HTML to re-extract from")

    # Read raw HTML from GCS (use a fresh storage client; small infra)
    bucket_name, _, blob_path = article.raw_html_gcs_uri.removeprefix("gs://").partition("/")
    html = gcs_storage.Client().bucket(bucket_name).blob(blob_path).download_as_text()

    # Delete existing doc so process() doesn't bail on duplicate.
    # Firestore wrapper does not expose delete; do it here intentionally.
    repo._client.collection("articles").document(
        article_id
    ).delete()  # intentional: no public delete API

    payload = IngestPayload(
        source=article.source,
        source_id=article.source_id,
        url=article.url,
        fetched_at=article.fetched_at,
        raw=RawHtml(kind="html", html=html),
    )
    svc = IngestService(repo=repo, extractor=extractor, archiver=archiver)
    return svc.process(payload)
