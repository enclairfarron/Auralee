# Data Source Strategy

**Reviewed:** 2026-07-21

Auralee should prefer sources that are programmatic, attributable, and stable over sources that
require generic article scraping. Every adapter should declare whether it provides full text,
summary text, or discovery metadata only, and retention must follow the source's license.

## Recommended integration order

### 1. SEC EDGAR — highest priority financial source

Use the official [EDGAR data APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
and filing RSS feeds for 8-K, 10-Q, 10-K, 6-K, Form 4, Form D, and S-1 events.

Why it fits Auralee:

- primary-source company disclosures rather than commentary;
- JSON APIs require no API key and are updated throughout the day;
- submissions include company names, exchanges, and ticker mappings;
- XBRL company facts can support earnings and fundamentals without another scraper.

Start with 8-K, 10-Q, and Form 4. Store filing metadata and extracted sections with accession
number as the immutable source ID. Respect SEC fair-access requirements and send an identifying
User-Agent.

### 2. AI first-party release monitor — highest priority AI-industry source

Track official announcement pages from:

- [OpenAI News](https://openai.com/news/)
- [Anthropic Newsroom](https://www.anthropic.com/news)
- [Google DeepMind News](https://deepmind.google/blog/)
- [AI at Meta](https://ai.meta.com/blog/)
- [NVIDIA RSS feeds](https://www.nvidia.com/en-us/about-nvidia/rss/)

These sources are best for model launches, partnerships, infrastructure announcements, safety
reports, and research releases. Prefer RSS or sitemaps when supplied; otherwise poll listing pages
lightly and retain only metadata plus text permitted by the source. NVIDIA's published RSS terms
currently restrict use to non-commercial informational use, so it needs a license review before a
commercial release.

### 3. arXiv + Hugging Face — AI research and open-source momentum

- Subscribe to official [arXiv RSS/Atom feeds](https://info.arxiv.org/help/rss.html), initially
  `cs.AI`, `cs.LG`, `cs.CL`, `cs.CV`, and `stat.ML`.
- Use the [arXiv metadata API](https://info.arxiv.org/help/api/index.html) for filtered queries and
  canonical metadata.
- Use the [Hugging Face Hub API](https://huggingface.co/docs/hub/en/api), webhooks, and paper
  endpoints for trending models, datasets, Spaces, and papers.

Do not send every paper through Gemini. Rank first using organization/author watchlists, code or
model availability, GitHub/Hugging Face momentum, and topic filters; extract only the top set.

### 4. GitHub release watchlists — implementation signal

Use the official [GitHub Releases API](https://docs.github.com/en/rest/releases/releases) for a
curated list such as PyTorch, JAX, Transformers, vLLM, llama.cpp, MLX, Ollama, and important model
provider SDKs. Releases are more useful and less noisy than generic GitHub Trending.

Store repository, tag, release timestamp, changelog, and asset links. Treat commits and stars as
supporting signals, not as financial sentiment.

### 5. FRED/ALFRED — macro context

Use the official [FRED API](https://fred.stlouisfed.org/docs/api/fred/overview.html) for rates,
inflation, employment, liquidity, and credit conditions. ALFRED vintages are useful when evaluating
historical signals without accidentally using later revisions. The API requires a key and has
specific attribution and terms.

FRED should become contextual data attached to articles and scorecards, not another article feed.

## Structured market-data and financial-news options

### Massive — recommended replacement candidate for yfinance

[Massive's current stock plans](https://massive.com/pricing?product=stocks) provide a free tier with
end-of-day data and two years of history; paid tiers add longer history, delayed or real-time data,
WebSockets, and higher limits. It also offers Benzinga partner datasets.

Recommended use: run a two-week shadow comparison against yfinance for missing bars, corporate
actions, timestamps, and adjusted returns before switching. Confirm whether the selected plan
permits the intended personal or commercial use.

### Alpha Vantage News & Sentiment — low-cost experiment option

The official [NEWS_SENTIMENT API](https://www.alphavantage.co/documentation/) supports ticker,
topic, time-range, and relevance filters and returns structured article metadata and sentiment.

Recommended use: a quick comparison source for signal-density and coverage experiments. Do not
treat its precomputed sentiment as ground truth for Auralee's own evaluator.

### Benzinga — production news candidate when budget and licensing are clear

The [Benzinga Newsfeed API](https://docs.benzinga.com/api-reference/news-api/overview) provides
structured timestamps, tickers, channels, topics, corrections/removals, and incremental polling.
Some plans can return full article bodies. This is operationally much safer than scraping media
sites, but pricing and display/storage rights must be agreed with the vendor.

Recommended use: evaluate only after free primary sources are running. It becomes attractive if
Auralee needs timely catalysts, earnings events, analyst actions, or "why is it moving" data.

### GDELT — discovery only

The [GDELT DOC API](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/) offers multilingual
global-news discovery, article lists, timelines, and machine-derived tone. It is useful for finding
AI policy, supply-chain, geopolitical, and international coverage that US feeds miss.

Recommended use: discovery and trend-volume signals. Expect high noise and link back to original
publishers; do not assume GDELT grants rights to republish article content.

## Sources not recommended for the next milestone

- More paywalled publisher scraping: it repeats the WSJ failure mode and creates licensing risk.
- Bloomberg scraping: hostile access controls and commercial-data restrictions make it unsuitable
  for a small PoC.
- Generic news APIs as the only source: they obscure provenance and often provide inconsistent
  timestamps or partial content.
- Newsletter inbox ingestion: valuable later for personal reading, but auth, forwarding, and
  content rights add complexity before the core experiment is validated.

## Common adapter contract

Before adding adapters, replace the current closed source literal with a source registry and map
every source into a source-neutral envelope before extraction:

```text
source_id, source, source_kind, canonical_url
title, author, published_at, fetched_at, language
content_scope = full | summary | metadata
content, entities_hint, tickers_hint
provenance, license_policy, raw_archive_allowed
```

`raw_archive_allowed` must control ingestion behavior, not remain descriptive metadata. Archive
the exact permitted extraction input when allowed; otherwise retain a content hash plus extraction
version and evaluate synchronously. Add source-health metrics for candidate count, fetch success,
usable-content rate, duplicate rate, latency, and cost. Evaluation should be segmented by `source`
and `content_scope`; a 250-character RSS summary must not be scored as if it were a full filing.

## Proposed next adapters

1. `sec_edgar`: 8-K and 10-Q metadata plus selected filing sections.
2. `ai_official`: first-party provider announcements from RSS/sitemap/listing adapters.
3. `arxiv`: filtered AI research metadata and abstracts.
4. `github_release`: curated repository releases.
5. `huggingface`: trending model/paper metadata.

Build the source registry and retention enforcement first. Then run the first two adapters in an
isolated shadow dataset during the fixed HN/MarketWatch P1 experiment; promote them only after the
baseline decision is recorded. They add differentiated, high-trust information while testing the
generalized adapter model without invalidating the current experiment.
