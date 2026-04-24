from fastapi.testclient import TestClient


def test_healthz_returns_ok(test_client: TestClient) -> None:
    response = test_client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
