from datetime import UTC, datetime
from unittest.mock import MagicMock

from app.services.gcs import RawHtmlArchiver


def test_archive_writes_to_correct_path() -> None:
    mock_blob = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    mock_client = MagicMock()
    mock_client.bucket.return_value = mock_bucket

    archiver = RawHtmlArchiver(bucket_name="auralee-api-server-raw", _client=mock_client)
    uri = archiver.upload(
        article_id="wsj_20260424_a3f1b9d2",
        source="wsj",
        published_at=datetime(2026, 4, 24, 13, 30, tzinfo=UTC),
        html="<html></html>",
    )

    mock_client.bucket.assert_called_once_with("auralee-api-server-raw")
    mock_bucket.blob.assert_called_once_with("wsj/2026-04-24/wsj_20260424_a3f1b9d2.html")
    mock_blob.upload_from_string.assert_called_once()
    args, kwargs = mock_blob.upload_from_string.call_args
    assert args[0] == "<html></html>"
    assert kwargs.get("content_type") == "text/html; charset=utf-8"
    assert uri == "gs://auralee-api-server-raw/wsj/2026-04-24/wsj_20260424_a3f1b9d2.html"
