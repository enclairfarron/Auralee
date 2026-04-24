from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import get_ingest_service, require_admin_token
from app.models.ingest import IngestPayload, IngestResponse
from app.services.ingest_service import IngestService

router = APIRouter(tags=["ingest"], dependencies=[Depends(require_admin_token)])


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    payload: IngestPayload,
    service: Annotated[IngestService, Depends(get_ingest_service)],
) -> IngestResponse:
    return service.process(payload)
