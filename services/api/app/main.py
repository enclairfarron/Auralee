from fastapi import FastAPI

from app.logging_setup import configure_logging
from app.routers import admin, cron, health, ingest


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="auralee-api", version="0.1.0")
    app.include_router(health.router)
    app.include_router(ingest.router)
    app.include_router(cron.router)
    app.include_router(admin.router)
    return app


app = create_app()
