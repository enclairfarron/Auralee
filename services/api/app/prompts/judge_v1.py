"""Judge prompt — version 1. Bump if semantics change meaningfully."""

JUDGE_PROMPT_VERSION = "v1"

JUDGE_SYSTEM_INSTRUCTION = """\
You are evaluating a structured extraction from a financial news article.

Given the article text and the extraction, rate 0-10 on overall quality, considering:
- tickers: precision (no hallucinations) and recall (no missed US-listed equities)
- sentiment: correctness for the primary subject
- summary: factual accuracy and completeness
- core_thesis: whether it captures the news angle

Respond with JSON of this shape:
{
  "score": <float 0-10>,
  "issues": [<short tag strings>],   // e.g. ["missing_ticker:TSLA", "wrong_sentiment", "hallucinated_ticker:XYZ"]
  "reasoning": <one short paragraph>
}

Be strict but fair. Score 10 only for flawless extractions. Score <=4 for material errors.
"""


def build_judge_user_message(article_url: str, clean_text: str, extraction_json: str) -> str:
    return (
        f"ARTICLE URL: {article_url}\n\n"
        f"ARTICLE TEXT:\n---\n{clean_text[:6000]}\n---\n\n"
        f"EXTRACTION (to evaluate):\n{extraction_json}\n\n"
        f"Return the evaluation JSON."
    )
