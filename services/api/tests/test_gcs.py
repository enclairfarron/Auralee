from datetime import UTC, datetime
from unittest.mock import MagicMock

from google.api_core.exceptions import PreconditionFailed

from app.models.ingest import RawText
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
    assert kwargs.get("if_generation_match") == 0
    assert uri == "gs://auralee-api-server-raw/wsj/2026-04-24/wsj_20260424_a3f1b9d2.html"


def test_archive_text_writes_canonical_utf8_json() -> None:
    mock_blob = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    mock_client = MagicMock()
    mock_client.bucket.return_value = mock_bucket
    archiver = RawHtmlArchiver(bucket_name="auralee-api-server-raw", _client=mock_client)

    uri = archiver.upload_text(
        article_id="reuters_20260424_a3f1b9d2",
        source="reuters",
        published_at=datetime(2026, 4, 24, 13, 30, tzinfo=UTC),
        raw_text=RawText(
            title="市场更新",
            body="苹果发布了新产品。",
            metadata={"z": 2, "a": "RSS"},
        ),
    )

    path = "reuters/2026-04-24/reuters_20260424_a3f1b9d2.json"
    mock_bucket.blob.assert_called_once_with(path)
    args, kwargs = mock_blob.upload_from_string.call_args
    assert args[0].decode("utf-8") == (
        '{"body":"苹果发布了新产品。","kind":"text",'
        '"metadata":{"a":"RSS","z":2},"title":"市场更新"}'
    )
    assert kwargs == {
        "content_type": "application/json; charset=utf-8",
        "if_generation_match": 0,
    }
    assert uri == f"gs://auralee-api-server-raw/{path}"


def test_safe_archive_returns_stable_uri_when_evidence_already_exists() -> None:
    archiver = RawHtmlArchiver(bucket_name="auralee-api-server-raw", _client=MagicMock())
    archiver.upload_text = MagicMock(side_effect=PreconditionFailed("already exists"))

    uri = archiver.upload_text_safe(
        article_id="hn_20260424_a3f1b9d2",
        source="hn",
        published_at=datetime(2026, 4, 24, tzinfo=UTC),
        raw_text=RawText(title="t", body="b", metadata={}),
    )

    assert uri == "gs://auralee-api-server-raw/hn/2026-04-24/hn_20260424_a3f1b9d2.json"
