from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
@router.get("/healthz", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}
