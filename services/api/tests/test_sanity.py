from app.services.sanity import check_ticker_precision


def test_passes_when_ticker_symbol_in_text() -> None:
    result = check_ticker_precision(
        tickers=["AAPL"],
        clean_text="Today AAPL reported earnings.",
    )
    assert result.ticker_precision_pass is True
    assert result.flags == []


def test_passes_when_company_name_in_text() -> None:
    result = check_ticker_precision(
        tickers=["AAPL"],
        clean_text="Today Apple Inc. reported earnings.",
    )
    assert result.ticker_precision_pass is True


def test_fails_with_hallucinated_ticker_flag() -> None:
    result = check_ticker_precision(
        tickers=["AAPL", "ZZZZ"],
        clean_text="Today AAPL reported earnings.",
    )
    assert result.ticker_precision_pass is False
    assert any("ZZZZ" in f for f in result.flags)


def test_empty_tickers_passes() -> None:
    result = check_ticker_precision(tickers=[], clean_text="some text")
    assert result.ticker_precision_pass is True


def test_case_insensitive_company_match() -> None:
    result = check_ticker_precision(tickers=["MSFT"], clean_text="microsoft beat...")
    assert result.ticker_precision_pass is True


def test_unknown_ticker_only_symbol_check() -> None:
    # Ticker not in dictionary → only check the symbol literal
    result = check_ticker_precision(tickers=["XYZQ"], clean_text="XYZQ surged today")
    assert result.ticker_precision_pass is True
