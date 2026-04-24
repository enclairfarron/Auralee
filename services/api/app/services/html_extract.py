import trafilatura


def extract_clean_text(html: str) -> str | None:
    if not html or not html.strip():
        return None
    return trafilatura.extract(
        html,
        include_comments=False,
        include_tables=False,
        favor_recall=False,
        no_fallback=False,
    )
