# V288 — Shorted API: measured capability on the free path

**Date:** 2026-08-28
**Author:** claude
**Status:** AUDIT — measured against the live public API, no strategy code, nothing pre-registered
**Parent:** [`V287.md`](V287.md) · [`V286_PHASE0_ASX.md`](V286_PHASE0_ASX.md)

---

## §1 — Access

Signed in at shorted.com.au via **Google OAuth**, which completed without a password
(the browser profile was already authenticated, so no consent screen appeared). No
password was typed and no account was created.

**A token could not be obtained on the free tier.** The dashboard's "Mint Token" control
is an anchor to the auth section, not a generator; `MintToken` is itself a *private*
endpoint; and the only real control is **"Subscribe to API Access" at $20/mo**
("Premium subscribers can create tokens here"). No purchase was made.

The earlier 403s were also explained: the docs state the edge rejects the default
`curl/...` agent with `permission_denied`. With a proper `User-Agent` and
`Connect-Protocol-Version: 1`, the public API answers without any token.

## §2 — What the anonymous tier actually returns

Measured directly, not inferred from the docs:

| Endpoint | Result |
|---|---|
| **`MarketService/GetMarketByDate`** | **200 with real values** — 740 securities per date, 50/page, `previousDate` chains backwards. e.g. `DRO` `percentageShorted=14.93`, `reportedShortPositions=137,982,780` |
| `StockService/GetStock` | 200 — **every field `None`**. The shape without the data. |
| `MarketService/GetTopShorts` | 200 — `percentageShorted` **null** |
| `MarketService/GetAvailableDates` | 200 — **only 90 dates, 2026-04-17 → 2026-08-21** |
| `NewsService/GetStockNews` | **400** `"product code is required"` on every field spelling tried, including the one `GetStock` accepts |

So the free path is *selectively* useful. One endpoint carries real data; the rest return
empty shapes, nulls, or errors. **Reading the rate-limit table alone would have given
entirely the wrong impression** — the tiers describe request budgets, not field-level
redaction, and only measurement surfaced the difference.

## §3 — The decisive limit: ~4 months of history

`GetAvailableDates` returns **90 dates**. Whatever the tier, this API is not a decade-deep
archive.

**It therefore does not solve the problem V287 §4 identified as blocking.** V286 §5
established that the ASX reversion finding may be pure survivorship bias, and testing that
needs a delisted-inclusive universe over ~10 years. Four months cannot answer it. The
hypothesis recorded in the client — that `GetMarketByDate` might supply point-in-time
history including delisted names — is **refuted on depth**, independently of whether it
includes delistings.

Nor does it deliver the news the brief asked for: `GetStockNews` is unavailable
anonymously, and V287 §1 already found no historical news on the free yfinance path.

## §4 — What it IS good for

A **740-name daily panel of ASIC short positions**, free, needing no token.

That is a genuinely broad universe — far better than the 20 hand-picked large caps V286
used, and broad enough to include small caps where short interest actually varies. Its
value is **forward**, not backward: freeze it daily from now and a survivorship-clean
panel accrues at ~250 observations/year, with delistings captured as they happen rather
than reconstructed.

That is precisely the V249 phase-transition argument — when the calendar bounds the
backtest, the only new independent data comes from the passage of time — applied to the
ASX instead of crypto. It is a slow answer, and it is a real one.

## §5 — The decision this leaves

Three options, none of which I can take unilaterally:

1. **$20/mo API Access** — unlocks token minting, private endpoints, 10,000 req/day. Worth
   it *only if* the paid tier also unlocks deeper history; §3 suggests the 90-date window
   may be a property of the dataset rather than the tier, and that should be confirmed
   with support before paying.
2. **Start the forward panel now, free.** Freeze `GetMarketByDate` daily for 740 names.
   Costs nothing, needs no token, and begins accruing the only data that can eventually
   answer §3. This is the V253 live-paper move.
3. **Acquire delisted-inclusive constituent history elsewhere.** Still the only thing that
   unblocks V286's headline finding, and still not something this API provides.

Options 2 and 3 are independent and both remain open. Option 1 should not be paid for on
the assumption that it deepens history — that is the thing to verify first.
