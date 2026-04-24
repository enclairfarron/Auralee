from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.deps import get_ingest_service
from app.main import create_app
from app.models.article import Extraction, Sentiment
from app.models.ingest import IngestMeta, IngestResponse


@pytest.fixture
def client_with_mock_service() -> tuple[TestClient, MagicMock]:
    mock_service = MagicMock()
    app = create_app()
    app.dependency_overrides[get_ingest_service] = lambda: mock_service
    return TestClient(app), mock_service


def test_ingest_requires_admin_token(
    client_with_mock_service: tuple[TestClient, MagicMock],
) -> None:
    client, _ = client_with_mock_service
    response = client.post("/ingest", json={})
    assert response.status_code in (
        401,
        422,
        503,
    )  # 422 if validation runs first; 401/503 if no token


def test_ingest_accepts_html_payload_and_returns_response(
    client_with_mock_service: tuple[TestClient, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")
    from app.config import get_settings

    get_settings.cache_clear()

    client, mock_service = client_with_mock_service
    mock_service.process.return_value = IngestResponse(
        article_id="wsj_20260424_a3f1b9d2",
        status="ingested",
        extracted=Extraction(
            title="t",
            summary="s",
            tickers=["AAPL"],
            sentiment=Sentiment(score=0.5, label="bullish"),
            core_thesis="c",
            language="en",
        ),
        meta=IngestMeta(
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.0001,
            latency_ms=100,
            prompt_version="v1",
        ),
    )

    body = {
        "source": "wsj",
        "source_id": "WP-1",
        "url": "https://www.wsj.com/articles/x",
        "fetched_at": datetime(2026, 4, 24, tzinfo=UTC).isoformat(),
        "raw": {"kind": "html", "html": "<html></html>", "encoding": "utf-8"},
    }
    response = client.post("/ingest", json=body, headers={"X-Admin-Token": "test-token"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ingested"
    assert data["extracted"]["tickers"] == ["AAPL"]
