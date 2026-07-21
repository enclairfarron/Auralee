# Charles Schwab Integration Plan

**Reviewed:** 2026-07-21
**Recommendation:** build read-only account context first; keep trading out of the initial MVP

## Feasibility

Schwab's [Developer Portal](https://developer.schwab.com/) currently offers **Trader API -
Individual** for an individual developer's own self-directed brokerage account. The product page
lists authentication, market data, account information, order/transaction information, order
entry, and order preview among its capabilities.

This makes a personal Auralee integration technically feasible. It does not authorize an
individual app to connect other users' brokerage accounts. If Auralee expands to invited users,
that capability must move to Schwab's commercial/retail-client integration path and its associated
approval and data-access terms.

## Security boundary

- Never ask for or store the user's Schwab username, password, MFA code, or session cookies.
- Use Schwab's OAuth authorization-code flow only.
- Treat native OAuth as a go/no-go gate: verify public-client support, PKCE, `state`, callback
  interception protections, and token-endpoint authentication. A desktop binary cannot safely
  contain a client secret; if Schwab requires one, exchange codes through a minimal backend token
  broker instead of embedding the secret.
- Open authorization in the system browser and require the user to select and approve accounts.
- Require an exactly registered callback URL; Schwab's public guide says callback URLs are used in
  the authorization-code flow and must match an app-registered URL.
- Prefer a local loopback or desktop deep-link callback if Schwab accepts it for the individual
  product. Otherwise use a minimal HTTPS callback broker and immediately hand control back to the
  desktop app.
- Store access and refresh tokens in macOS Keychain, not plaintext files, Firestore, logs, crash
  reports, or analytics.
- Encrypt the local portfolio database with a random Keychain-held key; exclude it from cloud
  backup, redact it from logs/crash reports, use atomic snapshots, and provide explicit retention,
  deletion, and unlink behavior.
- Keep Schwab API calls on the desktop where practical. Send the backend only the minimum derived
  portfolio context needed for ranking, such as ticker and coarse exposure bucket.
- Display and support revocation. A user remains in control of account access and should be able to
  unlink locally and through Schwab.

Schwab explicitly discourages credential-based screen scraping and describes tokenized API access
as the safer model. Its published terms also warn that third-party access changes the security and
privacy risk borne by the user, so the UI must explain what Auralee reads and stores.

## Phase S1 — Read-only personal portfolio context

Run the portal/OAuth feasibility spike after the P1 data-pipeline experiment and in parallel with
the desktop vertical slice. Implement portfolio sync only after the basic desktop journey is stable.

Capabilities:

- connect and disconnect one personal Schwab login;
- list authorized brokerage accounts using masked identifiers;
- sync positions, balances, and transaction history;
- build a local watchlist from held and recently traded symbols;
- rank news by current holdings and exposure;
- show "why this matters to my portfolio" with source citations;
- maintain a last-sync timestamp and clearly distinguish stale data.

Do not include order placement, cash transfer, options analytics, tax advice, or portfolio
recommendations in this phase.

### Minimal local data model

```text
broker_connection
  provider = schwab
  connection_id
  linked_at, last_synced_at, status
  keychain_token_reference

broker_account
  connection_id
  account_hash, display_mask, account_type
  selected_for_personalization

position_snapshot
  account_hash, symbol, asset_type
  quantity, market_value, portfolio_weight
  captured_at

broker_transaction
  provider_transaction_id, account_hash
  symbol, action, quantity, amount, occurred_at
```

Never persist a raw account number. Prefer the provider-issued account hash; if an endpoint exposes
only a raw identifier, derive a keyed HMAC locally with a random Keychain-held key, then discard the
raw value. Show only Schwab's masked display value.

## Phase S2 — Decision support without trading

- event alerts for holdings and recent trades;
- earnings, SEC filing, and material-news timelines per position;
- exposure-aware daily brief;
- explainable scenario analysis;
- user feedback on relevance and risk tolerance.

All output remains informational. The product should show data freshness, sources, and uncertainty
instead of presenting model output as a personalized investment instruction. Because holdings,
risk tolerance, and scenarios can still create personalized-advice risk, legal/compliance and
product-language review gates S2 before any beta release.

## Phase S3 — Optional trading, separate approval gate

Trading should be a separate project and remain disabled by default. If it is ever built:

- no autonomous or model-triggered order submission;
- require preview followed by explicit user confirmation for every order;
- no options, margin, short selling, or multi-leg orders in the first trading release;
- add symbol allowlists, quantity/notional caps, duplicate-order protection, and a kill switch;
- reconcile order state after submission and surface partial fills/rejections;
- keep an append-only local audit trail that excludes tokens and full account numbers;
- conduct a legal, security, and Schwab-product review before distribution.

The AI may draft an order ticket or explain a preview, but it must never be the final authority that
submits an order.

## Product consequences

The integration path depends on who uses Auralee:

- **Personal-only app:** Trader API - Individual is the appropriate starting point.
- **Friends or public users:** do not reuse the individual app credentials. Pursue Trader API -
  Commercial or an approved aggregation partner, with per-user OAuth consent and production review.

This decision should be made before implementing multi-user authentication because it changes
OAuth registration, token custody, privacy terms, support obligations, and the deployment model.

## Implementation spike

Before building UI, register an individual developer profile and a test app in Schwab's portal,
request the relevant product access, and verify:

1. eligible account types for the user's specific Schwab account;
2. whether the individual product supports a native public client with PKCE and no embedded secret;
3. accepted callback URL schemes and callback-interception protections for a Tauri/macOS app;
4. required `state`, token-endpoint authentication, access/refresh-token lifetime, and
   reauthorization behavior;
5. account, position, transaction, and market-data endpoint coverage;
6. sandbox versus production data behavior;
7. rate limits and any redistribution/storage restrictions.

Do not enter Schwab credentials into Auralee during this spike; authorization happens only on
Schwab-controlled pages.
