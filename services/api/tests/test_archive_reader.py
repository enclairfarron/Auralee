import json
from unittest.mock import MagicMock

import pytest

from app.services.archive_reader import ArchiveReadError, GCSArchivedContentReader


def _reader_with_content(content: str) -> tuple[GCSArchivedContentReader, MagicMock]:
    client = MagicMock()
    client.bucket.return_value.blob.return_value.download_as_text.return_value = content
    return GCSArchivedContentReader(_client=client), client


def test_reads_raw_text_json_as_original_extraction_surface() -> None:
    content = json.dumps(
        {
            "kind": "text",
            "title": "Apple earnings",
            "body": "Apple raised its full-year guidance.",
            "metadata": {"feed": "marketwatch"},
        }
    )
    reader, client = _reader_with_content(content)

    clean_text = reader.read_clean_text("gs://raw-bucket/reuters/2026-07-21/a.json")

    assert clean_text == "Apple earnings\n\nApple raised its full-year guidance."
    client.bucket.assert_called_once_with("raw-bucket")
    client.bucket.return_value.blob.assert_called_once_with("reuters/2026-07-21/a.json")


def test_reads_html_using_ingest_normalization() -> None:
    html = """
    <html><head><title>Ignored chrome</title></head><body><article>
      <h1>Nvidia launches a new chip</h1>
      <p>Nvidia announced a new accelerator for enterprise AI workloads.</p>
      <p>The company expects shipments to begin next quarter.</p>
    </article></body></html>
    """
    reader, _ = _reader_with_content(html)

    clean_text = reader.read_clean_text("gs://raw-bucket/hn/2026-07-21/a.html")

    assert "Nvidia launches a new chip" in clean_text
    assert "shipments to begin next quarter" in clean_text


def test_download_failure_is_reported_with_archive_uri() -> None:
    reader, client = _reader_with_content("")
    client.bucket.return_value.blob.return_value.download_as_text.side_effect = RuntimeError(
        "not found"
    )
    uri = "gs://raw-bucket/hn/2026-07-21/missing.html"

    with pytest.raises(ArchiveReadError, match="failed to download archived content") as exc_info:
        reader.read_clean_text(uri)

    assert uri in str(exc_info.value)


@pytest.mark.parametrize(
    ("uri", "content", "message"),
    [
        ("gs://raw-bucket/a.json", "not-json", "RawText JSON is invalid"),
        ("gs://raw-bucket/a.html", "<html></html>", "no extractable text"),
        ("gs://raw-bucket/a.txt", "article", "unsupported archived content type"),
        ("https://example.com/a.html", "article", "invalid GCS archive URI"),
    ],
)
def test_invalid_archive_is_rejected(uri: str, content: str, message: str) -> None:
    reader, _ = _reader_with_content(content)

    with pytest.raises(ArchiveReadError, match=message):
        reader.read_clean_text(uri)
