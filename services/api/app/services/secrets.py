from typing import Any

from google.cloud import secretmanager


class SecretClient:
    def __init__(self, project_id: str, _client: Any | None = None) -> None:
        self._project_id = project_id
        self._client = _client or secretmanager.SecretManagerServiceClient()
        self._cache: dict[str, str] = {}

    def get(self, name: str) -> str:
        if name not in self._cache:
            full_name = f"projects/{self._project_id}/secrets/{name}/versions/latest"
            response = self._client.access_secret_version({"name": full_name})
            self._cache[name] = response.payload.data.decode("utf-8")
        return self._cache[name]

    def invalidate(self, name: str) -> None:
        self._cache.pop(name, None)
