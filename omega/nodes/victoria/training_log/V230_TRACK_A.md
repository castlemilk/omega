# V230 Track A — options-implied skew data-vendor due diligence

**Date:** 2026-06-22
**Author:** claude (inline investigation; the subagent spawn 529'd twice, so the top-level Opus ran this track directly)
**Status:** due diligence only, NO vendor commitment. Web-sourced; prices flagged where unverified.
**Mandate:** find the cheapest path that could plausibly answer "does options-implied skew add crisis edge?" within 1–2 V### iterations, with strict recurring-cost discipline.

---

## TL;DR — A FREE MVP EXISTS, but it can only cover 2 of our 3 windows

**Loud headline:** Deribit's own **public, no-auth** API method `public/get_volatility_index_data` returns historical DVOL OHLC candles for free, and **CryptoDataDownload** publishes free DVOL OHLC CSVs for BTC & ETH. Either can be **one-shot frozen** into a per-window JSON snapshot per the V215 recipe at **$0 recurring cost**. **Do NOT buy a vendor to start.**

**The catch that reorders everything (verify before building):** **DVOL did not exist before ~March 2021.** That means:

| Window | DVOL available? | 25-Δ risk-reversal reconstructable? |
|---|---|---|
| 2020-Q1 (COVID) | ❌ **NO — index didn't exist** | ⚠️ only from raw options chains (Deribit data since 2019-03-30, paid Tardis Business) |
| 2022-H1 (LUNA/3AC) | ✅ yes | ✅ yes |
| 2026-04 (recent) | ✅ yes | ✅ yes |

So a free **DVOL** MVP can be tested on **2 of our 3 gates (trend + crisis-2022, recent)** but **not the 2020-Q1 crisis window**. Given Track C's finding that the crisis gate already sign-flips ±$16k across the two crisis windows, having only the 2022-H1 crisis window for DVOL is a real evidentiary weakness — but it is good enough for an MVP "does this even correlate with drawdowns?" probe.

**Recommendation:** **Free DVOL MVP (Deribit public endpoint), frozen per V215.** Do not spend. Only escalate to a paid vendor (Tardis Business, ~$300+ min) if the MVP shows a signal worth backfilling 2020-Q1 via raw-chain risk-reversal reconstruction.

---

## Paid vendors — fixed rubric

| Vendor | Cost ($/mo) | Data quality / window coverage | Integ. effort | Recurring? | Hermetic-freeze | Commit sample to private repo |
|---|---|---|---|---|---|---|
| **Tardis.dev** | No flat price; **$300 minimum order**; Options plan, tiered (Academic/Solo/Pro/Business). API replay needs **Pro/Business**. 4yr history on Solo/Pro, full since **2019-03-30** only on **Business** | Highest — tick-level raw options + order books; covers all 3 windows incl. 2020-Q1 via raw chains; risk-reversal must be **computed by us** (no pre-baked RR) | **L** (raw chains → compute 25-Δ RR ourselves) | **Subscription** (but can cancel after 1 freeze) | ✅ yes — CSV/JSON downloadable | ⚠️ unclear — redistribution terms; a small frozen derived sample is likely OK, verify ToS |
| **Amberdata** | Could not find published retail price (enterprise sales) | Very high — pre-baked DVOL index, term structure, skew, surface delta risk/reward; **history from 2021-05-21** (so NO 2020-Q1) | M (pre-baked analytics) | **Subscription**, enterprise | ✅ | ⚠️ unclear, enterprise ToS |
| **Kaiko** | Could not find published retail price (enterprise sales) | High — derivatives + options analytics; enterprise | M | **Subscription**, enterprise | ✅ | ⚠️ unclear |
| **Laevitas** | Could not find published price; has free tier (limited) | Pre-baked historical **risk-reversal** endpoint for Deribit (e.g. `/historical/options/type/risk_reversal/DERIBIT/BTC/10D`) — closest to exactly what we want | **S** (pre-baked RR) | Subscription / limited free | ✅ | ⚠️ unclear |

Notes: Tardis offers **free first-day-of-month CSVs** (no key) and **free trial accounts on request** — usable to validate quality before any spend. Tardis + Deribit also have a partnership offering some free historical data.

---

## Free alternatives — fixed rubric

| Source | Cost | What it gives / window coverage | Integ. effort | Hermetic-freeze | Commit to private repo |
|---|---|---|---|---|---|
| **Deribit public API** `public/get_volatility_index_data` | **$0, no auth** | DVOL OHLC candles; **from ~Mar 2021** → covers 2022-H1 + 2026-04, **NOT 2020-Q1** | **S** | ✅ one-shot JSON freeze per window | ✅ our own derived snapshot, low risk |
| **Deribit** `public/get_historical_volatility` | $0, no auth | **Realized** vol history (not implied) — useful sanity baseline | S | ✅ | ✅ |
| **CryptoDataDownload** | $0 | Free DVOL OHLC CSV, BTC & ETH | S | ✅ | ✅ (attribution) |
| **Glassnode** | Free tier exists | DVOL OHLC chart; implied-vol metrics gated to paid tiers | M | partial | ⚠️ |
| **nostoz / schepal GitHub** | $0 (OSS) | Compute risk-reversals/butterflies from live Deribit chains — **forward-only, no backfill** (Deribit serves no historical order books) | M-L | ✅ going forward only | ✅ |
| **DEX options (Lyra/Aevo/Premia/Hegic)** | $0 on-chain | Thin/illiquid IV; not comparable to Deribit depth; poor crisis coverage | L | partial | ✅ |
| **BlockScholes API** | Could not find free tier confirmation | Vol analytics | — | — | — |

**Key structural fact:** Deribit's API does **not** serve historical order books, so **pre-computed 25-Δ risk-reversal history cannot be pulled free** — it must either be (a) reconstructed from a paid raw-chain vendor (Tardis Business / Amberdata / Laevitas) or (b) accumulated live going forward. **DVOL, however, IS available free historically** (it's a published index, not order-book-derived on our side).

---

## Recommendation (detailed)

1. **V231/V232 MVP = free DVOL, no spend.** Freeze DVOL OHLC for BTC+ETH across 2022-H1 and 2026-04 via `public/get_volatility_index_data` (and the trend window), committed as JSON per V215. Build a **DVOL-derived additive brake** (e.g. DVOL z-score or DVOL term-structure / DVOL-vs-realized-vol premium) on the windows where it exists. Accept the 2020-Q1 gap explicitly.
2. **25-Δ risk-reversal (the truer skew signal) is NOT free historically.** If the DVOL MVP shows promise, the cheapest escalation is a **Tardis trial → one Business-month → freeze raw Deribit chains for all 3 windows → compute RR ourselves → cancel.** Treat it as a **one-time ~$300 data-acquisition spend**, not a subscription — freeze once, commit the derived snapshot, cancel. Verify redistribution ToS allows committing a small derived sample to a private repo before doing so.
3. **Do not engage Amberdata/Kaiko** (enterprise pricing, opaque, and Amberdata's 2021-05-21 start still misses 2020-Q1). Laevitas is the only paid option offering pre-baked RR with a free tier — worth a look only if DIY RR computation proves annoying.

**Bottom line for synthesis:** Track A does **not** justify any purchase now. There is a **free DVOL MVP**, but it (a) covers only 2/3 windows and (b) requires a fresh frozen-feed build regardless of source (our snapshots hold no options/IV history — confirmed by Track B). Given Track B found a **zero-cost, all-3-windows, additive-brake** signal already buildable from OHLCV we own, **the options-skew path is strictly inferior to Track B's #1 pick for V231** and should be parked as a V232+ candidate pending an MVP probe.

---

## Sources
- [Tardis.dev — Deribit historical data](https://docs.tardis.dev/historical-data-details/deribit)
- [Tardis.dev — Billing & Subscriptions](https://docs.tardis.dev/faq/billing-and-subscriptions)
- [Deribit Insights — DVOL Implied Volatility Index](https://insights.deribit.com/exchange-updates/dvol-deribit-implied-volatility-index/)
- [Deribit API docs](https://docs.deribit.com/)
- [Amberdata — Deribit market data / DVOL](https://www.amberdata.io/deribit-market-data)
- [Laevitas V1 API — historical options (risk_reversal)](https://docs.laevitas.ch/options/historical)
- [CryptoDataDownload — Deribit DVOL](https://www.cryptodatadownload.com/data/deribit/)
- [nostoz/deribit_volatility_download_and_visualize](https://github.com/nostoz/deribit_volatility_download_and_visualize)
