from unittest.mock import MagicMock

import pandas as pd
import pytest

from app.services.prices import refresh_prices


def _make_fake_df() -> pd.DataFrame:
    dates = pd.to_datetime(["2026-04-22", "2026-04-23", "2026-04-24"])
    return pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0],
            "High": [101.0, 102.0, 103.0],
            "Low": [99.0, 100.0, 101.0],
            "Close": [100.5, 101.5, 102.5],
            "Volume": [1000, 2000, 3000],
            "Adj Close": [100.5, 101.5, 102.5],
        },
        index=dates,
    )


@pytest.mark.asyncio
async def test_refresh_prices_writes_daily_ohlc_per_ticker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = MagicMock()
    repo.list_active_tickers.return_value = ["AAPL"]

    fake_df = _make_fake_df()
    # yfinance returns a single-level df for one ticker
    monkeypatch.setattr("app.services.prices._yf_download", lambda tickers, **kw: fake_df)

    summary = await refresh_prices(repo=repo)

    assert summary["refreshed"] == 1
    # 3 dates -> 3 save_daily_ohlc calls
    assert repo.save_daily_ohlc.call_count == 3
    repo.update_ticker_refreshed.assert_called_once()


@pytest.mark.asyncio
async def test_refresh_prices_noop_when_no_active_tickers() -> None:
    repo = MagicMock()
    repo.list_active_tickers.return_value = []
    summary = await refresh_prices(repo=repo)
    assert summary["status"] == "noop"
    repo.save_daily_ohlc.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_prices_handles_ticker_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = MagicMock()
    repo.list_active_tickers.return_value = ["AAPL", "BOGUS"]

    fake_df = _make_fake_df()

    def fake_download(tickers: list[str], **kw: object) -> pd.DataFrame:
        # Simulate multi-ticker shape: top-level cols are tickers
        arrays = [
            ["AAPL", "AAPL", "AAPL", "AAPL", "AAPL", "AAPL"],
            ["Open", "High", "Low", "Close", "Volume", "Adj Close"],
        ]
        cols = pd.MultiIndex.from_arrays(arrays)
        df = fake_df.copy()
        df.columns = cols
        # BOGUS column missing on purpose
        return df

    monkeypatch.setattr("app.services.prices._yf_download", fake_download)

    summary = await refresh_prices(repo=repo)
    # AAPL refreshed, BOGUS errored
    assert summary["refreshed"] == 1
    assert summary["errors"] == 1
