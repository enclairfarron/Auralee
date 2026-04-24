import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _set_admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "secret-test-token")
    from app.config import get_settings

    get_settings.cache_clear()


def test_admin_endpoint_rejects_missing_token(test_client: TestClient) -> None:
    response = test_client.get("/admin/articles")
    assert response.status_code == 401


def test_admin_endpoint_rejects_wrong_token(test_client: TestClient) -> None:
    response = test_client.get("/admin/articles", headers={"X-Admin-Token": "wrong"})
    assert response.status_code == 401


def test_admin_stats_404_when_no_metrics(
    test_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Bypass real Firestore by overriding get_repo
    from unittest.mock import MagicMock

    from app.deps import get_repo
    from app.main import create_app

    mock_repo = MagicMock()
    mock_repo.get_metrics.return_value = None
    app = create_app()
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    response = client.get(
        "/admin/stats?date=2026-04-24",
        headers={"X-Admin-Token": "secret-test-token"},
    )
    assert response.status_code == 404
