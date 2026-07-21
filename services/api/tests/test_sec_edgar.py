import copy
import json
from datetime import UTC, date, datetime
from importlib.resources import files
from typing import Any

import pytest

from app.services.sec_edgar import SecSubmissionsParseError, parse_sec_submissions


def _fixture() -> dict[str, Any]:
    raw = files("tests.data").joinpath("sec_submissions.json").read_text()
    return json.loads(raw)  # type: ignore[no-any-return]


def _single_row_payload() -> dict[str, Any]:
    return {
        "cik": 320193,
        "name": "Apple Inc.",
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-26-000081"],
                "filingDate": ["2026-07-20"],
                "acceptanceDateTime": ["2026-07-20T20:30:45Z"],
                "form": ["8-K"],
                "primaryDocument": ["aapl-20260720.htm"],
            }
        },
    }


def test_parses_exact_supported_forms_and_builds_canonical_urls() -> None:
    filings = parse_sec_submissions(_fixture())

    assert [filing.form for filing in filings] == ["8-K", "10-Q"]
    assert filings[0].source == "sec_edgar"
    assert filings[0].source_id == "0000320193-26-000081"
    assert filings[0].accession_number == filings[0].source_id
    assert filings[0].cik == "0000320193"
    assert filings[0].company_name == "Apple Inc."
    assert filings[0].canonical_url == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019326000081/aapl-20260720.htm"
    )


def test_acceptance_datetime_wins_and_filing_date_fallback_is_labelled() -> None:
    filings = parse_sec_submissions(_fixture())

    assert filings[0].published_at == datetime(2026, 7, 20, 20, 30, 45, tzinfo=UTC)
    assert filings[0].timestamp_quality == "acceptance_datetime"
    assert filings[1].filing_date == date(2026, 5, 1)
    assert filings[1].published_at == datetime(2026, 5, 1, tzinfo=UTC)
    assert filings[1].timestamp_quality == "filing_date_fallback"


def test_missing_acceptance_column_uses_filing_date_fallback() -> None:
    payload = _single_row_payload()
    del payload["filings"]["recent"]["acceptanceDateTime"]

    filing = parse_sec_submissions(payload)[0]

    assert filing.published_at == datetime(2026, 7, 20, tzinfo=UTC)
    assert filing.timestamp_quality == "filing_date_fallback"


def test_form_filter_is_exact_and_excludes_amendments_and_case_variants() -> None:
    payload = _single_row_payload()
    recent = payload["filings"]["recent"]
    recent["accessionNumber"] *= 4
    recent["filingDate"] *= 4
    recent["acceptanceDateTime"] *= 4
    recent["primaryDocument"] *= 4
    recent["form"] = ["8-K/A", "10-Q/A", "8-k", " 10-Q "]

    assert parse_sec_submissions(payload) == []


def test_rejects_misaligned_column_arrays_including_unknown_columns() -> None:
    payload = _single_row_payload()
    payload["filings"]["recent"]["items"] = ["2.02", "9.01"]

    with pytest.raises(SecSubmissionsParseError, match="column lengths differ"):
        parse_sec_submissions(payload)


def test_rejects_non_array_recent_column() -> None:
    payload = _single_row_payload()
    payload["filings"]["recent"]["items"] = "2.02"

    with pytest.raises(SecSubmissionsParseError, match="must be an array"):
        parse_sec_submissions(payload)


@pytest.mark.parametrize(
    "primary_document",
    [
        "",
        ".",
        "..",
        "../secret.htm",
        "/absolute.htm",
        "nested/report.htm",
        r"nested\report.htm",
        "report.htm?download=1",
        "report.htm#fragment",
        "%2e%2e%2freport.htm",
    ],
)
def test_rejects_unsafe_primary_document_paths(primary_document: str) -> None:
    payload = _single_row_payload()
    payload["filings"]["recent"]["primaryDocument"] = [primary_document]

    with pytest.raises(SecSubmissionsParseError, match="safe document basename"):
        parse_sec_submissions(payload)


@pytest.mark.parametrize(
    "accession",
    [
        "0000320193-26-000081/extra",
        "0000320193-2026-000081",
        "0000320194-26-000081",
        "320193-26-000081",
    ],
)
def test_rejects_noncanonical_or_wrong_cik_accessions(accession: str) -> None:
    payload = _single_row_payload()
    payload["filings"]["recent"]["accessionNumber"] = [accession]

    with pytest.raises(SecSubmissionsParseError, match="accessionNumber"):
        parse_sec_submissions(payload)


def test_rejects_malformed_nonempty_acceptance_datetime_instead_of_falling_back() -> None:
    payload = _single_row_payload()
    payload["filings"]["recent"]["acceptanceDateTime"] = ["2026-07-20 20:30:45"]

    with pytest.raises(SecSubmissionsParseError, match="timezone-aware ISO datetime"):
        parse_sec_submissions(payload)


@pytest.mark.parametrize("cik", ["", "12345678901", "12x", 0, -1, True, None])
def test_rejects_invalid_cik(cik: object) -> None:
    payload = _single_row_payload()
    payload["cik"] = cik

    with pytest.raises(SecSubmissionsParseError, match="cik"):
        parse_sec_submissions(payload)


def test_rejects_missing_required_recent_column() -> None:
    payload = copy.deepcopy(_single_row_payload())
    del payload["filings"]["recent"]["primaryDocument"]

    with pytest.raises(SecSubmissionsParseError, match="missing required columns"):
        parse_sec_submissions(payload)
