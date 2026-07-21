from typing import Any, Protocol

from google.cloud import storage  # type: ignore[attr-defined]
from pydantic import ValidationError

from app.models.ingest import RawText
from app.services.html_extract import extract_clean_text


class ArchiveReadError(RuntimeError):
    """The immutable article archive could not provide judgeable text."""


class ArchivedContentReader(Protocol):
    """Reader boundary used by the judge runner and its tests."""

    def read_clean_text(self, uri: str) -> str: ...


class GCSArchivedContentReader:
    """Load and normalize first-seen article evidence from Google Cloud Storage."""

    def __init__(self, _client: Any | None = None) -> None:
        self._client = _client if _client is not None else storage.Client()

    def read_clean_text(self, uri: str) -> str:
        bucket_name, blob_path = _parse_gcs_uri(uri)
        try:
            archived_content = (
                self._client.bucket(bucket_name).blob(blob_path).download_as_text(encoding="utf-8")
            )
        except Exception as exc:
            raise ArchiveReadError(
                f"failed to download archived content from {uri}: {exc}"
            ) from exc

        if blob_path.lower().endswith(".json"):
            return _clean_raw_text(archived_content, uri)
        if blob_path.lower().endswith(".html"):
            clean_text = extract_clean_text(archived_content)
            if not clean_text or not clean_text.strip():
                raise ArchiveReadError(f"archived HTML contains no extractable text: {uri}")
            return clean_text.strip()
        raise ArchiveReadError(f"unsupported archived content type: {uri}")


def _parse_gcs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ArchiveReadError(f"invalid GCS archive URI: {uri}")
    bucket_name, separator, blob_path = uri.removeprefix("gs://").partition("/")
    if not separator or not bucket_name or not blob_path:
        raise ArchiveReadError(f"invalid GCS archive URI: {uri}")
    return bucket_name, blob_path


def _clean_raw_text(archived_content: str, uri: str) -> str:
    try:
        raw_text = RawText.model_validate_json(archived_content)
    except ValidationError as exc:
        raise ArchiveReadError(f"archived RawText JSON is invalid: {uri}") from exc

    parts = [raw_text.title.strip(), raw_text.body.strip()]
    clean_text = "\n\n".join(dict.fromkeys(part for part in parts if part))
    if not clean_text:
        raise ArchiveReadError(f"archived RawText contains no text: {uri}")
    return clean_text
