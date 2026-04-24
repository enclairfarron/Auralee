from fastapi import Depends, FastAPI

from app.deps import require_admin_token
from app.routers import health


def create_app() -> FastAPI:
    app = FastAPI(title="auralee-api", version="0.1.0")
    app.include_router(health.router)

    @app.get("/_test/admin-echo", dependencies=[Depends(require_admin_token)])
    async def _admin_echo() -> dict[str, bool]:
        return {"ok": True}

    return app


app = create_app()
