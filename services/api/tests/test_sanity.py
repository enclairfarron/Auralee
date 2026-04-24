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


def test_short_symbol_does_not_substring_match() -> None:
    # "V" must not match "vehicle" or "V8"
    result = check_ticker_precision(tickers=["V"], clean_text="The V8 engine in vehicles is fast.")
    assert result.ticker_precision_pass is False
    result = check_ticker_precision(tickers=["MA"], clean_text="MAJOR announcement coming.")
    assert result.ticker_precision_pass is False
    result = check_ticker_precision(tickers=["GS"], clean_text="GSA contract awarded today.")
    assert result.ticker_precision_pass is False


def test_lowercase_symbol_matches() -> None:
    # Real headlines normalize case sometimes ("aapl reported")
    result = check_ticker_precision(tickers=["AAPL"], clean_text="aapl reported earnings beat.")
    assert result.ticker_precision_pass is True


def test_ticker_with_punctuation_around() -> None:
    # $AAPL, (AAPL), AAPL., AAPL,
    for text in ["$AAPL surged.", "(AAPL) reported.", "AAPL, the iPhone maker.", "AAPL."]:
        result = check_ticker_precision(tickers=["AAPL"], clean_text=text)
        assert result.ticker_precision_pass is True, f"failed on: {text}"


def test_v_matches_when_actually_present() -> None:
    # Sanity: don't over-correct — actual Visa mention should still pass
    result = check_ticker_precision(
        tickers=["V"], clean_text="Visa Inc. (NYSE: V) reported strong earnings."
    )
    assert result.ticker_precision_pass is True
