import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _set_admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "secret-test-token")
    from app.config import get_settings

    get_settings.cache_clear()


def test_protected_endpoint_rejects_missing_token(test_client: TestClient) -> None:
    # /_test/admin-echo is added in main.py — the test echo route exercises require_admin_token
    response = test_client.get("/_test/admin-echo")
    assert response.status_code == 401


def test_protected_endpoint_rejects_wrong_token(test_client: TestClient) -> None:
    response = test_client.get("/_test/admin-echo", headers={"X-Admin-Token": "wrong"})
    assert response.status_code == 401


def test_protected_endpoint_accepts_correct_token(test_client: TestClient) -> None:
    response = test_client.get("/_test/admin-echo", headers={"X-Admin-Token": "secret-test-token"})
    assert response.status_code == 200
    assert response.json() == {"ok": True}
