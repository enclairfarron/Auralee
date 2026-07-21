from datetime import UTC, datetime
from unittest.mock import ANY, MagicMock

import pytest

from app.models.article import Extraction, Sentiment
from app.models.ingest import IngestPayload, RawHtml, RawText
from app.services.gemini import ExtractionResult
from app.services.ingest_service import IngestService


@pytest.fixture
def sample_extraction() -> Extraction:
    return Extraction(
        title="Apple Q2",
        summary="Apple beat earnings.",
        tickers=["AAPL"],
        sentiment=Sentiment(score=0.7, label="bullish"),
        core_thesis="Apple Q2 EPS beat.",
        categories=["earnings"],
        entities=[],
        language="en",
    )


@pytest.fixture
def sample_extraction_result(sample_extraction: Extraction) -> ExtractionResult:
    return ExtractionResult(
        extraction=sample_extraction,
        tokens_in=1000,
        tokens_out=200,
        cost_usd=0.0001,
        latency_ms=200,
        prompt_version="v1",
        model="gemini-2.5-flash",
    )


@pytest.fixture
def html_payload() -> IngestPayload:
    return IngestPayload(
        source="wsj",
        source_id="x",
        url="https://www.wsj.com/articles/apple-q2",
        published_at=datetime(2026, 4, 23, 23, 30, tzinfo=UTC),
        fetched_at=datetime(2026, 4, 24, 13, 30, tzinfo=UTC),
        raw=RawHtml(
            kind="html",
            html=(
                "<html><body><article>"
                + "Apple Inc. reported strong earnings. " * 60
                + "</article></body></html>"
            ),
        ),
    )


def test_duplicate_returns_status_duplicate_without_calling_gemini(
    html_payload: IngestPayload,
) -> None:
    repo = MagicMock()
    repo.article_exists.return_value = True
    extractor = MagicMock()
    archiver = MagicMock()
    svc = IngestService(repo=repo, extractor=extractor, archiver=archiver)

    response = svc.process(html_payload)

    assert response.status == "duplicate"
    extractor.extract.assert_not_called()
    repo.save_article.assert_not_called()


def test_allow_existing_reprocesses_and_reuses_archive(
    html_payload: IngestPayload,
    sample_extraction_result: ExtractionResult,
) -> None:
    repo = MagicMock()
    repo.article_exists.return_value = True
    extractor = MagicMock()
    extractor.extract.return_value = sample_extraction_result
    archiver = MagicMock()
    svc = IngestService(repo=repo, extractor=extractor, archiver=archiver)

    response = svc.process(
        html_payload,
        allow_existing=True,
        existing_article_id="legacy-article-id",
        existing_archive_uri="gs://bucket/original.html",
    )

    assert response.status == "ingested"
    extractor.extract.assert_called_once()
    repo.save_article.assert_called_once()
    archiver.upload_safe.assert_not_called()
    archiver.upload_text_safe.assert_not_called()
    saved = repo.save_article.call_args.args[0]
    assert response.article_id == "legacy-article-id"
    assert saved.id == "legacy-article-id"
    assert saved.raw_content_gcs_uri == "gs://bucket/original.html"
    assert saved.raw_html_gcs_uri == "gs://bucket/original.html"


def test_allow_existing_does_not_overwrite_article_when_extraction_fails(
    html_payload: IngestPayload,
) -> None:
    repo = MagicMock()
    repo.article_exists.return_value = True
    extractor = MagicMock()
    extractor.extract.side_effect = RuntimeError("Vertex unavailable")
    archiver = MagicMock()
    svc = IngestService(repo=repo, extractor=extractor, archiver=archiver)

    with pytest.raises(RuntimeError, match="Vertex unavailable"):
        svc.process(
            html_payload,
            allow_existing=True,
            existing_archive_uri="gs://bucket/original.html",
        )

    repo.save_article.assert_not_called()
    archiver.upload_safe.assert_not_called()


def test_short_text_returns_skipped_short(html_payload: IngestPayload) -> None:
    repo = MagicMock()
    repo.article_exists.return_value = False
    extractor = MagicMock()
    archiver = MagicMock()
    svc = IngestService(repo=repo, extractor=extractor, archiver=archiver)

    short = html_payload.model_copy(
        update={"raw": RawHtml(kind="html", html="<html><body>short</body></html>")}
    )
    response = svc.process(short)

    assert response.status == "skipped_short"
    extractor.extract.assert_not_called()


def test_text_payload_skips_html_extraction(
    sample_extraction_result: ExtractionResult,
) -> None:
    repo = MagicMock()
    repo.article_exists.return_value = False
    extractor = MagicMock()
    extractor.extract.return_value = sample_extraction_result
    archiver = MagicMock()
    archiver.upload_text_safe.return_value = "gs://bucket/x.json"

    payload = IngestPayload(
        source="hn",
        source_id="42",
        url="https://news.ycombinator.com/item?id=42",
        fetched_at=datetime(2026, 4, 24, tzinfo=UTC),
        raw=RawText(kind="text", title="t", body="x" * 1000, metadata={}),
    )
    svc = IngestService(repo=repo, extractor=extractor, archiver=archiver)
    response = svc.process(payload)

    assert response.status == "ingested"
    archiver.upload_safe.assert_not_called()
    archiver.upload_text_safe.assert_called_once_with(
        article_id=response.article_id,
        source="hn",
        published_at=payload.fetched_at,
        raw_text=payload.raw,
    )
    assert response.meta is not None
    assert response.meta.raw_content_gcs_uri == "gs://bucket/x.json"
    assert response.meta.raw_html_gcs_uri is None
    saved = repo.save_article.call_args.args[0]
    assert saved.raw_content_gcs_uri == "gs://bucket/x.json"
    assert saved.raw_html_gcs_uri is None
    extractor.extract.assert_called_once()
    assert extractor.extract.call_args.kwargs["clean_text"].startswith("t\n\n")


def test_html_happy_path_writes_article_and_returns_extracted(
    html_payload: IngestPayload,
    sample_extraction_result: ExtractionResult,
) -> None:
    repo = MagicMock()
    repo.article_exists.return_value = False
    extractor = MagicMock()
    extractor.extract.return_value = sample_extraction_result
    archiver = MagicMock()
    archiver.upload_safe.return_value = "gs://bucket/x.html"

    svc = IngestService(repo=repo, extractor=extractor, archiver=archiver)
    response = svc.process(html_payload)

    assert response.status == "ingested"
    assert response.article_id.startswith("wsj_20260423_")
    assert response.extracted is not None
    assert response.extracted.tickers == ["AAPL"]
    assert response.meta is not None
    assert response.meta.cost_usd == 0.0001
    assert response.meta.raw_content_gcs_uri == "gs://bucket/x.html"
    assert response.meta.raw_html_gcs_uri == "gs://bucket/x.html"

    repo.save_article.assert_called_once()
    saved = repo.save_article.call_args[0][0]
    assert saved.published_at == html_payload.published_at
    assert saved.fetched_at == html_payload.fetched_at
    assert saved.raw_content_gcs_uri == "gs://bucket/x.html"
    assert saved.raw_html_gcs_uri == "gs://bucket/x.html"
    assert saved.tickers == ["AAPL"]
    assert saved.sanity_check is not None
    assert saved.sanity_check.ticker_precision_pass is True

    repo.upsert_ticker_stub.assert_called_with("AAPL")
    extractor.extract.assert_called_once_with(
        source="wsj",
        url="https://www.wsj.com/articles/apple-q2",
        published_at="2026-04-23T23:30:00+00:00",
        clean_text=ANY,
    )
    assert isinstance(html_payload.raw, RawHtml)
    archiver.upload_safe.assert_called_once_with(
        article_id=response.article_id,
        source="wsj",
        published_at=html_payload.fetched_at,
        html=html_payload.raw.html,
    )


def test_missing_published_at_falls_back_to_fetched_at(
    sample_extraction_result: ExtractionResult,
) -> None:
    repo = MagicMock()
    repo.article_exists.return_value = False
    extractor = MagicMock()
    extractor.extract.return_value = sample_extraction_result
    archiver = MagicMock()
    archiver.upload_text_safe.return_value = None
    fetched_at = datetime(2026, 4, 24, 1, 30, tzinfo=UTC)
    payload = IngestPayload(
        source="hn",
        source_id="42",
        url="https://example.com/story",
        fetched_at=fetched_at,
        raw=RawText(kind="text", title="Story", body="Apple " * 100, metadata={}),
    )

    response = IngestService(repo=repo, extractor=extractor, archiver=archiver).process(payload)

    assert response.article_id.startswith("hn_20260424_")
    saved = repo.save_article.call_args.args[0]
    assert saved.published_at == fetched_at
    assert saved.fetched_at == fetched_at
    assert extractor.extract.call_args.kwargs["published_at"] == fetched_at.isoformat()
