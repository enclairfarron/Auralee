from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.deps import (
    get_http_client,
    get_ingest_service,
    get_judge,
    get_repo,
    get_secrets,
    require_admin_token,
)
from app.services.firestore_repo import FirestoreRepo
from app.services.ingest_service import IngestService
from app.services.judge import GeminiJudge
from app.services.judge_runner import run_eval_judge
from app.services.metrics_runner import aggregate_yesterday_metrics
from app.services.prices import refresh_prices
from app.services.scrape_runner import run_scrape
from app.services.scrapers.base import BaseScraper
from app.services.scrapers.hn import HNScraper
from app.services.scrapers.reuters import ReutersScraper
from app.services.scrapers.wsj import WSJScraper
from app.services.secrets import SecretClient

router = APIRouter(
    prefix="/cron",
    tags=["cron"],
    dependencies=[Depends(require_admin_token)],
)


@router.post("/scrape")
async def cron_scrape(
    source: Annotated[Literal["hn", "reuters", "wsj"], Query()],
    http: Annotated[httpx.AsyncClient, Depends(get_http_client)],
    secrets: Annotated[SecretClient, Depends(get_secrets)],
    ingest: Annotated[IngestService, Depends(get_ingest_service)],
    repo: Annotated[FirestoreRepo, Depends(get_repo)],
) -> Any:
    scraper: BaseScraper
    if source == "hn":
        scraper = HNScraper(http=http)
        delay = 0.0
    elif source == "reuters":
        scraper = ReutersScraper(http=http)
        delay = 1.0
    else:
        scraper = WSJScraper(http=http, cookie=secrets.get("WSJ_COOKIE"))
        delay = 2.0

    result = await run_scrape(
        scraper=scraper,
        ingest=ingest,
        repo=repo,
        candidate_limit=30 if source == "hn" else 50,
        fetch_delay_seconds=delay,
    )
    # Cloud Scheduler treats any 2xx response as a successful delivery. Surface
    # a total source failure as 503 so retry/alerting semantics match the saved run.
    if result["status"] == "failure":
        return JSONResponse(status_code=503, content=result)
    return result


@router.post("/refresh-prices")
async def cron_refresh_prices(
    repo: Annotated[FirestoreRepo, Depends(get_repo)],
) -> dict[str, Any]:
    return await refresh_prices(repo=repo)


@router.post("/eval-judge")
async def cron_eval_judge(
    repo: Annotated[FirestoreRepo, Depends(get_repo)],
    judge: Annotated[GeminiJudge, Depends(get_judge)],
) -> dict[str, Any]:
    return await run_eval_judge(repo=repo, judge=judge)


@router.post("/aggregate-metrics")
async def cron_aggregate_metrics(
    repo: Annotated[FirestoreRepo, Depends(get_repo)],
) -> dict[str, Any]:
    return await aggregate_yesterday_metrics(repo=repo)
