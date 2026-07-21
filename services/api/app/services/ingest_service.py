import logging
from datetime import UTC, datetime

from app.models.article import Article, GeminiMeta
from app.models.ingest import IngestMeta, IngestPayload, IngestResponse, RawHtml
from app.services.article_id import compute_article_id
from app.services.firestore_repo import FirestoreRepo
from app.services.gcs import RawHtmlArchiver
from app.services.gemini import GeminiExtractor
from app.services.html_extract import extract_clean_text
from app.services.sanity import check_ticker_precision

logger = logging.getLogger(__name__)

# Lowered from 500 -> 200 to accommodate RSS-description-only sources
# (MarketWatch where Cloud Run can't HTTP-fetch full articles due to anti-bot 401).
# WSJ paywall HTML extracts to <500 chars but is detected separately by the
# WSJ scraper's keyword check, so this lower bound doesn't weaken paywall detection.
_MIN_CLEAN_TEXT_CHARS = 200


class IngestService:
    def __init__(
        self,
        repo: FirestoreRepo,
        extractor: GeminiExtractor,
        archiver: RawHtmlArchiver,
    ) -> None:
        self._repo = repo
        self._extractor = extractor
        self._archiver = archiver

    def process(
        self,
        payload: IngestPayload,
        *,
        allow_existing: bool = False,
        existing_article_id: str | None = None,
        existing_archive_uri: str | None = None,
    ) -> IngestResponse:
        # Older callers may not know the publication time. Keep them compatible,
        # but prefer the source-provided timestamp whenever it is available.
        published_at = payload.published_at or payload.fetched_at
        article_id = existing_article_id or compute_article_id(
            payload.source, published_at, payload.url
        )

        if self._repo.article_exists(article_id) and not allow_existing:
            logger.info("ingest skipped: duplicate", extra={"article_id": article_id})
            return IngestResponse(article_id=article_id, status="duplicate")

        # Normalize to clean text
        if isinstance(payload.raw, RawHtml):
            clean_text = extract_clean_text(payload.raw.html) or ""
        else:
            text_parts = [payload.raw.title.strip(), payload.raw.body.strip()]
            # RSS titles often contain the most precise company/product name.
            # Keep them in the extraction input, while deduplicating HN fallbacks
            # that intentionally use the same text as both title and body.
            clean_text = "\n\n".join(dict.fromkeys(part for part in text_parts if part))

        if len(clean_text) < _MIN_CLEAN_TEXT_CHARS:
            logger.info(
                "ingest skipped: short text",
                extra={"article_id": article_id, "chars": len(clean_text)},
            )
            return IngestResponse(article_id=article_id, status="skipped_short")

        # Archive the exact extraction input before Gemini processing. GCS writes
        # are create-only so this remains first-seen evaluation evidence.
        raw_content_gcs_uri: str | None
        raw_html_gcs_uri: str | None = None
        if isinstance(payload.raw, RawHtml):
            raw_html_gcs_uri = existing_archive_uri
            if raw_html_gcs_uri is None:
                raw_html_gcs_uri = self._archiver.upload_safe(
                    article_id=article_id,
                    source=payload.source,
                    # The archive is a fetch artifact, so partition it by fetch date.
                    published_at=payload.fetched_at,
                    html=payload.raw.html,
                )
            raw_content_gcs_uri = raw_html_gcs_uri
        else:
            raw_content_gcs_uri = existing_archive_uri
            if raw_content_gcs_uri is None:
                raw_content_gcs_uri = self._archiver.upload_text_safe(
                    article_id=article_id,
                    source=payload.source,
                    published_at=payload.fetched_at,
                    raw_text=payload.raw,
                )

        # Gemini extraction
        result = self._extractor.extract(
            source=payload.source,
            url=payload.url,
            published_at=published_at.isoformat(),
            clean_text=clean_text,
        )

        # M2 sanity check
        sanity = check_ticker_precision(
            tickers=result.extraction.tickers,
            clean_text=clean_text,
        )

        now = datetime.now(UTC)
        article = Article(
            id=article_id,
            source=payload.source,
            source_id=payload.source_id,
            url=payload.url,
            title=result.extraction.title,
            published_at=published_at,
            fetched_at=payload.fetched_at,
            processed_at=now,
            language=result.extraction.language,
            raw_content_gcs_uri=raw_content_gcs_uri,
            raw_html_gcs_uri=raw_html_gcs_uri,
            clean_text_chars=len(clean_text),
            summary=result.extraction.summary,
            tickers=result.extraction.tickers,
            sentiment=result.extraction.sentiment,
            core_thesis=result.extraction.core_thesis,
            categories=result.extraction.categories,
            entities=result.extraction.entities,
            gemini_meta=GeminiMeta(
                model=result.model,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                cost_usd=result.cost_usd,
                latency_ms=result.latency_ms,
                prompt_version=result.prompt_version,
            ),
            sanity_check=sanity,
        )
        self._repo.save_article(article)

        for ticker in result.extraction.tickers:
            self._repo.upsert_ticker_stub(ticker)

        return IngestResponse(
            article_id=article_id,
            status="ingested",
            extracted=result.extraction,
            meta=IngestMeta(
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                cost_usd=result.cost_usd,
                latency_ms=result.latency_ms,
                prompt_version=result.prompt_version,
                raw_content_gcs_uri=raw_content_gcs_uri,
                raw_html_gcs_uri=raw_html_gcs_uri,
            ),
        )
