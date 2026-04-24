import json
from datetime import UTC, datetime
from functools import lru_cache
from importlib.resources import files
from typing import cast

from app.models.article import SanityCheck


@lru_cache(maxsize=1)
def _ticker_dictionary() -> dict[str, list[str]]:
    raw = files("app.data").joinpath("tickers.json").read_text()
    return cast(dict[str, list[str]], json.loads(raw))


def _ticker_found_in_text(ticker: str, clean_text: str) -> bool:
    text_lower = clean_text.lower()
    if ticker.upper() in clean_text:
        return True
    aliases = _ticker_dictionary().get(ticker.upper(), [])
    return any(alias.lower() in text_lower for alias in aliases)


def check_ticker_precision(tickers: list[str], clean_text: str) -> SanityCheck:
    flags: list[str] = []
    for t in tickers:
        if not _ticker_found_in_text(t, clean_text):
            flags.append(f"hallucinated_ticker:{t}")
    return SanityCheck(
        ticker_precision_pass=len(flags) == 0,
        checked_at=datetime.now(UTC),
        flags=flags,
    )
