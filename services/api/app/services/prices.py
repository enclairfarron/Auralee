import logging
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import yfinance as yf

from app.models.price import DailyOHLC
from app.models.run import Run, RunError
from app.services.firestore_repo import FirestoreRepo

logger = logging.getLogger(__name__)


def _yf_download(tickers: list[str], **kw: Any) -> pd.DataFrame:
    """Indirection so tests can monkeypatch."""
    return yf.download(tickers, progress=False, **kw)


def _iter_ticker_frames(data: pd.DataFrame, tickers: list[str]) -> dict[str, pd.DataFrame]:
    """Normalize yf.download output (single-ticker vs multi) into ticker -> DataFrame."""
    if len(tickers) == 1:
        return {tickers[0]: data}
    result: dict[str, pd.DataFrame] = {}
    if isinstance(data.columns, pd.MultiIndex):
        # MultiIndex columns: level 0 = ticker, level 1 = field
        for t in tickers:
            if t in data.columns.get_level_values(0):
                result[t] = data[t]
    return result


async def refresh_prices(repo: FirestoreRepo) -> dict[str, Any]:
    run = Run(id="", kind="refresh-prices", started_at=datetime.now(UTC))
    tickers = repo.list_active_tickers()
    if not tickers:
        run.status = "noop"
        run.finished_at = datetime.now(UTC)
        repo.save_run(run)
        return {"status": "noop", "refreshed": 0, "errors": 0}

    try:
        data = _yf_download(
            tickers,
            period="1mo",
            group_by="ticker",
            auto_adjust=False,
            threads=True,
        )
    except Exception as e:
        run.status = "failure"
        run.errors.append(RunError(stage="yf.download", message=str(e)[:200]))
        run.finished_at = datetime.now(UTC)
        repo.save_run(run)
        return {"status": "failure", "refreshed": 0, "errors": 1}

    frames = _iter_ticker_frames(data, tickers)

    for ticker in tickers:
        df = frames.get(ticker)
        if df is None or df.empty:
            run.errors.append(RunError(ticker=ticker, stage="extract", message="no data"))
            continue
        try:
            df = df.dropna(subset=["Close"])
            for date_idx, row in df.iterrows():
                ohlc = DailyOHLC(
                    date=pd.Timestamp(date_idx).date().isoformat(),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=int(row["Volume"]),
                    adj_close=float(row["Adj Close"]),
                    fetched_at=datetime.now(UTC),
                    source="yfinance",
                )
                repo.save_daily_ohlc(ticker, ohlc)
            repo.update_ticker_refreshed(ticker, datetime.now(UTC))
            run.refreshed += 1
        except Exception as e:
            run.errors.append(RunError(ticker=ticker, stage="write", message=str(e)[:200]))

    run.finished_at = datetime.now(UTC)
    run.status = (
        "partial" if run.errors and run.refreshed > 0 else ("failure" if run.errors else "success")
    )
    repo.save_run(run)
    return {
        "status": run.status,
        "refreshed": run.refreshed,
        "errors": len(run.errors),
    }
