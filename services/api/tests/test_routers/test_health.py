from fastapi.testclient import TestClient


def test_health_returns_ok_with_legacy_alias(test_client: TestClient) -> None:
    for path in ("/health", "/healthz"):
        response = test_client.get(path)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
