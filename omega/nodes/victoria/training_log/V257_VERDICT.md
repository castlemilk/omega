# V257 — On-chain Data-Acquisition Freeze — VERDICT

**Date:** 2026-07-15 · **Author:** claude (Opus 4.8) · **Type:** data-freeze execution verdict (no strategy code)
**Runbook:** [`V257_EXECUTION_RUNBOOK.md`](V257_EXECUTION_RUNBOOK.md) · **Pre-reg:** [`V257.md`](V257.md)
**Unblocks:** [`V256.md`](V256.md) (on-chain flow primary universe) · **Parent:** [`V254_ALT_DATA_SCOPING.md`](V254_ALT_DATA_SCOPING.md) Track C

## Verdict: **SUCCESS — V256 UNBLOCKED (4 of 4 signals frozen, byte-identical).**

The Coin Metrics **community** tier (free, no API key) delivered **all 4** of V256's
pre-declared on-chain signals as frozen, per-asset, ≥3-year daily series for {BTC, ETH}.
The V257 falsifier gate (≥3 of 4 signals, ≥3-year daily coverage, byte-identical
re-freeze) **passes on every count**. V256 is re-registrable as a buildable offline bet.

---

## 1 — Freeze pipeline execution summary

- **Script:** `scripts/v257_freeze_on_chain.py` (new; data-only, no strategy code touched).
  Mirrors `scripts/v238_freeze_series.py` — one network pull, canonical JSON, MD5-checked,
  manifest-updating. Stdlib-only (`urllib`/`json`/`hashlib`).
- **Source:** `https://community-api.coinmetrics.io/v4/timeseries/asset-metrics`,
  community tier, `frequency=1d`, cursor pagination, 0.15 s inter-request sleep.
- **Assets:** BTC, ETH. **Span requested:** 2020-01-01 → 2026-07-14.
- **Output:** `data/frozen_series/on_chain/{BTC,ETH}/{metric}.json` + `{metric}.json.md5`
  sidecar per file + shared `MANIFEST.json`.
- **Runtime:** ~12 s (network-bound; `page_size=10000` fits each 2387-row series in one page).
- **12 series frozen, 2387 obs each, 0 missing days.**

### Preflight (Phase 0) — egress + tier reality-check

- Egress test (`AdrActCnt`, BTC, one week) → **HTTP 200** with a valid `data` array. Egress OK.
- **Catalog reality-check changed the metric set** vs. the runbook's assumptions:
  the runbook's `FlowInBTC`/`FlowOutBTC` are **invalid metric ids (HTTP 400)**, and its
  `TxTfrValNtv`/`SplyAct1yr` are **paid-tier (HTTP 403)**. The catalog-v2 endpoint
  (`community:true` filter) surfaced the correct free substitutes, which cover all four
  V256 signals. This is the runbook's anticipated "confirm exactly which metrics are
  community-available before freezing" step (Step 2b) resolving to a better-than-expected
  outcome: **exchange flow is free on the community tier.**

### Signal → Coin Metrics community-metric mapping (as frozen)

| V256 signal | CM community metric(s) | Meaning |
|---|---|---|
| #1 net exchange netflow | `FlowInExNtv` − `FlowOutExNtv` | native-unit supply on/off exchanges/day |
| #2 active-address velocity | `AdrActCnt` | distinct active addresses/day |
| #3 whale-cluster movement | `SplyExNtv` | native-unit supply held on exchanges (accumulation/distribution proxy) |
| #4 transaction volume | `TxTfrCnt` (+ `TxCnt`) | transfers/day (+ tx count) — network usage |

> **Proxy note (#3).** True whale-cohort clustering is Glassnode/Santiment paid-tier.
> `SplyExNtv` (exchange-held supply) is the honest community proxy for large-holder
> accumulation/distribution; documented here so the V256 builder treats it as a proxy,
> not ground-truth whale flow. **Anti-Goodhart:** the signal SET is whatever the free
> tier delivered — V256 is run as pre-registered over these signals, not redesigned to
> fit them.

## 2 — Coverage table (per metric, per asset)

| Asset | File | CM metric | V256 signal | First | Last | N obs | Missing | MD5 |
|---|---|---|---|---|---|---|---|---|
| BTC | active_addresses | AdrActCnt | active_address_velocity | 2020-01-01 | 2026-07-14 | 2387 | 0 | `f4c2f741c9b36d457c7f827958af37c7` |
| BTC | exchange_inflow_native | FlowInExNtv | net_exchange_netflow | 2020-01-01 | 2026-07-14 | 2387 | 0 | `7292bff53c2187e0a574381ddd33cb52` |
| BTC | exchange_outflow_native | FlowOutExNtv | net_exchange_netflow | 2020-01-01 | 2026-07-14 | 2387 | 0 | `3f2768ea8bf03f599434de8f5621a7aa` |
| BTC | exchange_supply_native | SplyExNtv | whale_cluster_movement | 2020-01-01 | 2026-07-14 | 2387 | 0 | `a7b1a4cf94402d50ebed978cfe4c74a1` |
| BTC | transaction_count | TxCnt | transaction_volume | 2020-01-01 | 2026-07-14 | 2387 | 0 | `d4fe6cb5f7166cf8d150f0d8f0afcf41` |
| BTC | transfer_count | TxTfrCnt | transaction_volume | 2020-01-01 | 2026-07-14 | 2387 | 0 | `766c6bec09c630fb6e17a020f0dc7a14` |
| ETH | active_addresses | AdrActCnt | active_address_velocity | 2020-01-01 | 2026-07-14 | 2387 | 0 | `12d0493101f3aea3fc223854958359d5` |
| ETH | exchange_inflow_native | FlowInExNtv | net_exchange_netflow | 2020-01-01 | 2026-07-14 | 2387 | 0 | `f9db91c84136064994b7e7da680e8815` |
| ETH | exchange_outflow_native | FlowOutExNtv | net_exchange_netflow | 2020-01-01 | 2026-07-14 | 2387 | 0 | `4aa0acbf7ff4b3ab07a549fb3ba79013` |
| ETH | exchange_supply_native | SplyExNtv | whale_cluster_movement | 2020-01-01 | 2026-07-14 | 2387 | 0 | `1249d1dcd61e8698e7c7e5d8c72b7f82` |
| ETH | transaction_count | TxCnt | transaction_volume | 2020-01-01 | 2026-07-14 | 2387 | 0 | `16cdc2f0d2e4e2b1998eb7d2d73dedb8` |
| ETH | transfer_count | TxTfrCnt | transaction_volume | 2020-01-01 | 2026-07-14 | 2387 | 0 | `baedf0bf4c3ac1c508e224b611a0eb0f` |

- **Coverage:** every series spans **6.5 years** (2020-01-01 → 2026-07-14) — well past the
  3-year falsifier floor.
- **Cadence:** daily; **0 missing days** vs. calendar (gap fraction 0.0% on all 12 series).

## 3 — MD5 stability (byte-identity, V257 falsifier #2)

Re-ran the full freeze into a scratch dir (`/tmp/v257_refreeze/`) and compared per-file
MD5s against the committed set:

```
files compared: 12  identical: 12  mismatched: 0
RESULT: BYTE-IDENTICAL — falsifier #2 clears
```

Determinism is structural, not luck: the per-series JSON files carry **no wall-clock
field** (provenance `frozen_at_utc` lives only in `MANIFEST.json`, which is excluded
from the byte-identity diff), values are stored as the **raw decimal strings** returned
by the API (lossless, float-round-trip-independent), and serialization is canonical
(sorted keys, compact separators, `PYTHONHASHSEED`-independent). A `.json.md5` sidecar
is written alongside each series and `md5sum -c` verifies clean.

## 4 — V256 unblock confirmation

Re-ran the V256 Phase-0 data audit against `data/frozen_series/on_chain/`:

```
signal 1 net_exchange_netflow      per-asset[BTC:Y ETH:Y] -> PRESENT
signal 2 active_address_velocity   per-asset[BTC:Y ETH:Y] -> PRESENT
signal 3 whale_cluster_movement    per-asset[BTC:Y ETH:Y] -> PRESENT
signal 4 transaction_volume        per-asset[BTC:Y ETH:Y] -> PRESENT
RESULT: 4 of 4 V256 signals frozen per-asset (was 1 of 4)
GATE (>=3 of 4): PASS — V256 UNBLOCKED
```

- [`V256.md`](V256.md) verdict updated: **PAUSED → UNBLOCKED (re-registrable as buildable).**
- [`V254_ALT_DATA_SCOPING.md`](V254_ALT_DATA_SCOPING.md) Track C updated:
  **PAUSED (needs data acquisition) → PRIMARY offline (buildable).**

## 5 — Falsifier gate summary

| V257 falsifier | Threshold | Result |
|---|---|---|
| #1 coverage | ≥3-year daily per signal | **PASS** — 6.5yr, 0 gaps, all 12 |
| #2 reproducibility | byte-identical re-freeze MD5 | **PASS** — 12/12 identical |
| signal count | ≥3 of 4 V256 signals, per-asset | **PASS** — 4/4, both assets |

**All gates pass. V256 reopens as buildable.**

## Scope / integrity ledger (what this task did and did NOT do)

- **DID:** add `scripts/v257_freeze_on_chain.py`; freeze 12 series (+ md5 sidecars +
  manifest) under `data/frozen_series/on_chain/`; update V256/V254 status docs; write
  this verdict.
- **Did NOT:** build V256 (the flow-primary scorer + walk-forward is a follow-on V###);
  touch strategy code (`strategy.py`, `signal_generation.py`, `victoria_node.py`) or any
  flag; touch the running live-paper daemon; touch V255-related paths; run any
  live-broker anything. **$0 spent** (community tier is free).

## Next (follow-on, NOT this task)

Build the V256 flow-primary offline composite over the frozen signals, cross-sectional
across {BTC, ETH}, walk-forwarded and gated **exactly as V256 pre-registered** — no
post-hoc redesign to fit the arrived data. Optional later: escalate to a paid tier
(Glassnode/CryptoQuant) for true exchange-netflow + whale cohorts **only if** the
community MVP clears the V256 falsifier first.
