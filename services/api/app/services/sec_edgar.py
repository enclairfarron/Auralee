"""Pure parser for the SEC EDGAR company submissions JSON format.

This module deliberately has no HTTP, routing, or persistence concerns.  A caller
must fetch and decode the submissions document before passing it here.
"""

import re
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict

SecForm = Literal["8-K", "10-Q"]
TimestampQuality = Literal["acceptance_datetime", "filing_date_fallback"]

_SUPPORTED_FORMS: frozenset[str] = frozenset({"8-K", "10-Q"})
_ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_FILING_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ACCEPTANCE_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_PRIMARY_DOCUMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_REQUIRED_RECENT_COLUMNS = frozenset({"accessionNumber", "filingDate", "form", "primaryDocument"})


class SecSubmissionsParseError(ValueError):
    """Raised when an SEC submissions document violates the expected schema."""


class SecFiling(BaseModel):
    """A supported filing parsed from ``filings.recent``.

    SEC accession numbers are globally stable filing identifiers, so ``source_id``
    intentionally remains the accession number rather than a title or URL hash.
    """

    model_config = ConfigDict(frozen=True)

    source: Literal["sec_edgar"] = "sec_edgar"
    source_id: str
    cik: str
    company_name: str | None = None
    form: SecForm
    accession_number: str
    filing_date: date
    published_at: datetime
    timestamp_quality: TimestampQuality
    primary_document: str
    canonical_url: str


def parse_sec_submissions(payload: Mapping[str, object]) -> list[SecFiling]:
    """Parse exact 8-K and 10-Q rows from an SEC submissions document.

    Amendments such as 8-K/A and 10-Q/A are excluded by exact form matching.
    All arrays in ``filings.recent`` must have equal length so a malformed SEC
    column set can never silently associate values from different filings.
    """

    cik = _normalize_cik(payload.get("cik"))
    company_name = _optional_nonempty_string(payload.get("name"), "name")

    filings = _require_mapping(payload.get("filings"), "filings")
    recent = _require_mapping(filings.get("recent"), "filings.recent")
    columns, row_count = _validate_recent_columns(recent)

    acceptance_column = columns.get("acceptanceDateTime")
    results: list[SecFiling] = []
    for index in range(row_count):
        form_value = columns["form"][index]
        if not isinstance(form_value, str):
            raise SecSubmissionsParseError(f"filings.recent.form[{index}] must be a string")
        if form_value not in _SUPPORTED_FORMS:
            continue

        accession = _parse_accession(columns["accessionNumber"][index], cik, index)
        filing_date = _parse_filing_date(columns["filingDate"][index], index)
        accepted_value = acceptance_column[index] if acceptance_column is not None else None
        published_at, timestamp_quality = _parse_published_at(accepted_value, filing_date, index)
        primary_document = _parse_primary_document(columns["primaryDocument"][index], index)

        results.append(
            SecFiling(
                source_id=accession,
                cik=cik,
                company_name=company_name,
                form=cast(SecForm, form_value),
                accession_number=accession,
                filing_date=filing_date,
                published_at=published_at,
                timestamp_quality=timestamp_quality,
                primary_document=primary_document,
                canonical_url=_canonical_filing_url(cik, accession, primary_document),
            )
        )

    return results


def _normalize_cik(value: object) -> str:
    if isinstance(value, bool):
        raise SecSubmissionsParseError("cik must be a positive integer or digit string")
    if isinstance(value, int):
        raw = str(value)
    elif isinstance(value, str):
        raw = value
    else:
        raise SecSubmissionsParseError("cik must be a positive integer or digit string")

    if not raw or not raw.isascii() or not raw.isdigit() or len(raw) > 10 or int(raw) <= 0:
        raise SecSubmissionsParseError("cik must contain 1 to 10 ASCII digits and be positive")
    return raw.zfill(10)


def _require_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SecSubmissionsParseError(f"{field} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise SecSubmissionsParseError(f"{field} keys must be strings")
    return value


def _optional_nonempty_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise SecSubmissionsParseError(f"{field} must be a non-empty string when present")
    return value


def _validate_recent_columns(
    recent: Mapping[str, object],
) -> tuple[dict[str, list[object]], int]:
    missing = sorted(_REQUIRED_RECENT_COLUMNS.difference(recent))
    if missing:
        raise SecSubmissionsParseError(
            f"filings.recent is missing required columns: {', '.join(missing)}"
        )

    columns: dict[str, list[object]] = {}
    expected_length: int | None = None
    for name, raw_column in recent.items():
        if not isinstance(raw_column, list):
            raise SecSubmissionsParseError(f"filings.recent.{name} must be an array")
        column = list(raw_column)
        if expected_length is None:
            expected_length = len(column)
        elif len(column) != expected_length:
            raise SecSubmissionsParseError(
                "filings.recent column lengths differ: "
                f"{name} has {len(column)}, expected {expected_length}"
            )
        columns[name] = column

    return columns, expected_length or 0


def _parse_accession(value: object, cik: str, index: int) -> str:
    if not isinstance(value, str) or not _ACCESSION_RE.fullmatch(value):
        raise SecSubmissionsParseError(
            f"filings.recent.accessionNumber[{index}] is not a canonical accession number"
        )
    if value[:10] != cik:
        raise SecSubmissionsParseError(
            f"filings.recent.accessionNumber[{index}] does not match submissions CIK"
        )
    return value


def _parse_filing_date(value: object, index: int) -> date:
    if not isinstance(value, str) or not _FILING_DATE_RE.fullmatch(value):
        raise SecSubmissionsParseError(f"filings.recent.filingDate[{index}] must use YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SecSubmissionsParseError(
            f"filings.recent.filingDate[{index}] is not a valid date"
        ) from exc


def _parse_published_at(
    acceptance_value: object, filing_date: date, index: int
) -> tuple[datetime, TimestampQuality]:
    if acceptance_value is None or acceptance_value == "":
        return datetime.combine(
            filing_date, datetime.min.time(), tzinfo=UTC
        ), "filing_date_fallback"
    if not isinstance(acceptance_value, str) or not _ACCEPTANCE_DATETIME_RE.fullmatch(
        acceptance_value
    ):
        raise SecSubmissionsParseError(
            f"filings.recent.acceptanceDateTime[{index}] must be a timezone-aware ISO datetime"
        )
    try:
        parsed = datetime.fromisoformat(acceptance_value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SecSubmissionsParseError(
            f"filings.recent.acceptanceDateTime[{index}] is not a valid datetime"
        ) from exc
    if parsed.tzinfo is None:
        raise SecSubmissionsParseError(
            f"filings.recent.acceptanceDateTime[{index}] must include a timezone"
        )
    return parsed.astimezone(UTC), "acceptance_datetime"


def _parse_primary_document(value: object, index: int) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 255
        or not _PRIMARY_DOCUMENT_RE.fullmatch(value)
        or value in {".", ".."}
    ):
        raise SecSubmissionsParseError(
            f"filings.recent.primaryDocument[{index}] is not a safe document basename"
        )
    return value


def _canonical_filing_url(cik: str, accession: str, primary_document: str) -> str:
    cik_without_zero_padding = str(int(cik))
    accession_without_hyphens = accession.replace("-", "")
    return (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{cik_without_zero_padding}/{accession_without_hyphens}/{primary_document}"
    )
