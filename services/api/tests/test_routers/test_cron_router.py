from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def cron_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ADMIN_TOKEN", "secret-test-token")

    from app.config import get_settings
    from app.deps import get_http_client, get_ingest_service, get_repo, get_secrets
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_http_client] = lambda: MagicMock()
    app.dependency_overrides[get_ingest_service] = lambda: MagicMock()
    app.dependency_overrides[get_repo] = lambda: MagicMock()
    app.dependency_overrides[get_secrets] = lambda: MagicMock()
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


@pytest.mark.parametrize(
    ("run_status", "expected_http_status"),
    [("success", 200), ("partial", 200), ("noop", 200), ("failure", 503)],
)
def test_scrape_http_status_matches_run_outcome(
    cron_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    run_status: str,
    expected_http_status: int,
) -> None:
    summary = {
        "kind": "scrape",
        "source": "hn",
        "status": run_status,
        "attempted": 0,
        "ingested": 0,
        "skipped_dup": 0,
        "skipped_short": 0,
        "outcome_counts_complete": True,
        "errors": 1 if run_status == "failure" else 0,
        "cost_usd": 0.0,
        "started_at": "2026-07-21T00:00:00+00:00",
        "finished_at": "2026-07-21T00:00:01+00:00",
    }
    run = AsyncMock(return_value=summary)
    monkeypatch.setattr("app.routers.cron.run_scrape", run)

    response = cron_client.post(
        "/cron/scrape?source=hn",
        headers={"X-Admin-Token": "secret-test-token"},
    )

    assert response.status_code == expected_http_status
    assert response.json() == summary
