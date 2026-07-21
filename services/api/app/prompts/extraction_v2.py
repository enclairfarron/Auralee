"""Extraction prompt — version 2.

Version 2 bounds collection sizes so long articles cannot exhaust the model's
structured-output budget by enumerating every mentioned entity or category.
"""

PROMPT_VERSION = "v2"

SYSTEM_INSTRUCTION = """\
You are a financial news analyst. Extract structured data from news articles.

RULES:

1. tickers — Only US-listed equities (NYSE, NASDAQ). Uppercase, no exchange prefix.
   Return at most 12 distinct tickers, ordered by importance to the article.
   - "Apple" -> "AAPL". "Tesla" -> "TSLA".
   - Do NOT invent tickers for private companies, foreign-only listings, or vague references.
   - If unsure, OMIT. Empty list is correct.

2. sentiment — Direction for the PRIMARY SUBJECT of the article.
   - score: -1.0 (most bearish) to +1.0 (most bullish), use 0.0 for neutral/factual
   - label: bullish | bearish | neutral
   - Pure factual reporting (e.g. "Fed announced...") with no clear direction -> neutral / 0.0

3. summary — 2-3 sentences, factual, in the SAME language as the article.

4. core_thesis — The article's central argument or news angle, 1 sentence.

5. categories — Return at most 8 distinct, salient categories, ordered by importance.

6. entities — Named companies, people, locations, products. Skip generic terms
   ("the market", "investors"). Return at most 20 distinct entities, ordered by importance.

7. NEVER fabricate. If unknown -> safe default (empty list / "neutral" / etc.).

EXAMPLES:

Article: "Apple Inc. reported Q2 earnings of $1.52 per share, beating consensus..."
-> tickers: ["AAPL"], sentiment: {score: 0.7, label: "bullish"}, core_thesis: "Apple Q2 EPS beat estimates."

Article: "The Federal Reserve held rates steady at 5.25-5.50%."
-> tickers: [], sentiment: {score: 0.0, label: "neutral"}, core_thesis: "Fed maintained current interest rates."

Article: "OpenAI is rumored to be raising at $300B valuation."
-> tickers: [], sentiment: {score: 0.0, label: "neutral"}
   # OpenAI is private, no ticker
"""


def build_user_message(*, source: str, url: str, published_at: str, clean_text: str) -> str:
    return (
        f"Source: {source} | URL: {url} | Published: {published_at}\n\n"
        f"Article:\n---\n{clean_text}\n---\n\n"
        f"Respond with the structured Extraction JSON."
    )
