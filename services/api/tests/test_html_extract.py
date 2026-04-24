from importlib.resources import files

from app.services.html_extract import extract_clean_text


def _load_sample() -> str:
    return files("tests.data").joinpath("wsj_sample.html").read_text()


def test_extracts_main_body_skipping_nav_footer() -> None:
    html = _load_sample()
    text = extract_clean_text(html)
    assert text is not None
    assert "Apple Inc." in text
    assert "iPhone sales" in text
    assert "Sign In" not in text
    assert "Copyright Dow Jones" not in text


def test_returns_none_for_empty_html() -> None:
    assert extract_clean_text("") is None


def test_returns_none_for_garbage_html() -> None:
    # No body content => trafilatura returns None
    assert extract_clean_text("<html></html>") is None
