from unittest.mock import MagicMock

import pytest

from app.services.secrets import SecretClient


def test_get_uses_latest_alias_and_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_response = MagicMock()
    mock_response.payload.data = b"super-secret-value"
    mock_client = MagicMock()
    mock_client.access_secret_version.return_value = mock_response

    sc = SecretClient(project_id="proj", _client=mock_client)
    assert sc.get("WSJ_COOKIE") == "super-secret-value"
    assert sc.get("WSJ_COOKIE") == "super-secret-value"  # cached, no re-call

    mock_client.access_secret_version.assert_called_once()
    args, _ = mock_client.access_secret_version.call_args
    assert args[0]["name"] == "projects/proj/secrets/WSJ_COOKIE/versions/latest"


def test_invalidate_forces_refresh() -> None:
    mock_response = MagicMock()
    mock_response.payload.data = b"v1"
    mock_client = MagicMock()
    mock_client.access_secret_version.return_value = mock_response

    sc = SecretClient(project_id="proj", _client=mock_client)
    sc.get("X")
    sc.invalidate("X")
    sc.get("X")
    assert mock_client.access_secret_version.call_count == 2
