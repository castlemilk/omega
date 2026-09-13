# V307 — ASX intraday: does the trading day have a recurring shape, and is any of it worth a trade?

**Date:** 2026-09-13
**Status:** PRE-REGISTERED — Phase 0 audit + 1h freeze + time-of-day map. Results blank below until the run is done.
**Parent:** V304 (ASX verdict) / V306 (latest entry)
**Data unlock:** resume path (2) from `V249.md` / `CAMPAIGN_STATUS.md` — "a new data source that changes regime structure (intraday OHLCV freeze)" — applied to the ASX line rather than to Victoria.

---

## 1. Why this version exists

V304 closed the ASX line with a verdict, not a strategy: the short-interest neglect
premium is real (Q1−Q5 +0.298%/wk, t = +2.85) and concentrates in exactly the names
where impact makes it unharvestable. Its §4 named the only two things that could
change that — a measured impact coefficient k, or *a cheaper way to hold the
exposure* — and said explicitly that neither is "more analysis of this data".

This version does not re-analyse that data. It adds a resolution the ASX line has
never had. Every ASX result so far, V286→V304, was computed on daily closes, and the
operator's question — *are there recurring intraday patterns, pre-lunch trades and
the like?* — cannot be asked of a daily bar at all.

Two honest framings, both pre-declared:

1. **As pattern discovery**, this is the first map of the ASX trading day the
   campaign has. The deliverable is the map, whether or not a bar clears cost.
2. **As a path to trading**, an intraday seasonality is a candidate for V304 §4(2):
   an *execution-timing overlay* on the one configuration that survived costs
   (quarterly, whole universe). Knowing *when* in the day to rebalance is a way to
   reduce the impact that eats the edge — it needs no new alpha, only a volume and
   drift profile. That is V308's candidate, and is not tested here.

## 2. What the data can and cannot be

Measured 2026-09-13, before writing this:

| source | resolution | depth | notes |
|---|---|---|---|
| shorted.com.au (MCP + frozen v3) | daily | prices 2015→, shorts 2010→ | no intraday; 1,941 PIT codes, 1,005 priced |
| yfinance `.AX` | **1h** | **730 days** (2023-10-26 → now) | 7 bars/session at 10:00…16:00 Sydney |
| yfinance `.AX` | 5m / 15m | 60 days | last stamp 16:10 = closing-auction print |
| yfinance `.AX` | 1m | 7 days | unusable for anything but a smoke test |

The 1h corpus is the study substrate. It is **two calendar years**, which fixes what
this version can claim: a within-sample split into two non-overlapping years is the
only out-of-sample test available, and a pattern that appears in both is "recurring
over two years", not "a law of the ASX".

**yfinance is a rolling window, not an archive.** A re-download next month returns a
different 730 days. So freeze-once discipline here means: download ONCE, write
provenance-stamped gzipped JSON with `mtime=0` (the V262 writer), record md5s in a
manifest, and `--verify` **hashes the committed files against the manifest** — it
never re-downloads, because a re-download cannot be byte-identical. Recorded so
nobody later reads a verify PASS as "the source still agrees".

The 5m corpus (60 days) is frozen for **audit only** — to confirm the 1h bar
boundaries and to see where "lunch" actually is at finer resolution. It is not a
test substrate at 60 days and nothing below gates on it.

## 3. Universe (pre-declared, point-in-time)

Top **120** codes by median AUD dollar-volume over the 250 sessions ending
**2023-10-26** (the first day of the 1h window), computed from the frozen v3
substrate — so membership is chosen with information available at the *start* of the
window, not the end. Threshold at rank 120: ~$4.7M/day; rank 100: ~$8.0M/day.

Probe result before freezing: **118 of 120 have full 1h coverage.** Two holes, both
recorded rather than dropped — CTD (Corporate Travel Management, 3,266 of ~5,080
bars; taken over mid-window) and NSR (National Storage REIT, delisted; yfinance
returns nothing). The survivorship hole for this study is therefore 2/120, and the
study universe is the 118 (CTD included for the sessions it has).

This is a **liquid-large-cap** universe by construction. It is the right one for a
time-of-day map (the patterns, if any, must exist where they could be traded) and
the wrong one for the thin-tercile neglect premium — that is a different question
and not this version's.

## 4. Buckets (pre-declared)

Sydney local time. A session has seven 1h bars stamped 10:00…16:00; the 16:00 bar
covers the 16:00–16:10 closing auction (5m data shows a 16:10 print, and the 16:00
bar carries ~3× the volume of any continuous hour in the probe).

| bucket | definition | what it is |
|---|---|---|
| `ON` | open(10:00 bar) / close(prev 16:00 bar) − 1 | overnight, including the opening auction |
| `B10` | close(10:00) / open(10:00) − 1 | first hour, from the opening print |
| `B11` | close(11:00) / close(10:00) − 1 | **11:00–12:00 — the "pre-lunch" hour** |
| `B12` | close(12:00) / close(11:00) − 1 | 12:00–13:00 — lunch |
| `B13` | close(13:00) / close(12:00) − 1 | 13:00–14:00 |
| `B14` | close(14:00) / close(13:00) − 1 | 14:00–15:00 |
| `B15` | close(15:00) / close(14:00) − 1 | 15:00–16:00 — last continuous hour |
| `B16` | close(16:00) / close(15:00) − 1 | **closing auction** |

Rules carried from the ASX line, applied here without exception:

- **A missing bar is excluded, never defaulted** (V303). A session missing any bar
  contributes nothing to the buckets that need it; it is counted, not filled.
- **`ON` is excluded on ex-dividend days**, detected from the frozen v3 daily series
  (adjusted_close/close ratio changing versus the previous session). Intraday bars
  are unadjusted, and an ex-div overnight gap is a dividend, not a pattern.
- **Read the metadata the response returns about itself** (V302): stamps outside
  the seven expected are a defect to report, and the bar count per session is
  asserted, not assumed.

The unit of observation is the **equal-weight daily bucket return** — the
cross-sectional mean across names for one bucket on one date. That gives ~720
observations per bucket, one per session, and the cross-sectional pooling absorbs
the same-day correlation across names that would otherwise inflate a pooled t.

## 5. Falsifiers (pre-declared, evaluated in this order)

**F1 — the corpus is a corpus.** ≥ 97% of (name, session) pairs carry all seven
stamps; no stamp outside the set; zero NaN closes among retained bars; the 16:00
bar's median volume share ≥ 15% of the session (it is the auction, or the bar
boundaries are not what I think). **FAIL ⇒ stop; nothing below is measured.**

**F2 — a bucket is a recurring pattern** iff, on its EW daily series,
|t| ≥ **3.0** over the full span (Bonferroni across 8 buckets ≈ p < 0.003 per
bucket) **and** the same sign with |t| ≥ **1.5** in each half
(H1 = 2023-10-26→2024-12-31, H2 = 2025-01-01→end). Either condition alone is not a
pattern. Reported for all 8 whether or not they pass.

**F3 — a pattern is worth a trade** iff its |mean| ≥ **20 bps** per occurrence —
V286's ASX round-trip retail cost, unchanged — or, for a run of adjacent buckets
with the same sign, the cumulative signed mean ≥ 20 bps. Sensitivity at 5 bps
(one-tick spread, institutional) is *reported*, not the bar.

**Pre-declared expectation, so it cannot be retrofitted:** F3 is expected to
**FAIL for every bucket.** Hourly mean drifts on large caps are single-digit bps.
If F2 passes and F3 fails, that is the same shape as V304 — real, unharvestable at
this cost — and the verdict on trading the ASX from this data **does not move**.
The value of that outcome is §1's framing 2: a map for execution timing.

**Secondary, declared as a family of 3 (Bonferroni within the family, |t| ≥ 2.4),
reported but not gating:**

- **S1 — gap reversal.** `B10` conditional on the sign of `ON`: does the first hour
  fade the overnight gap? Long-minus-short conditional mean, EW daily series.
- **S2 — intraday momentum into the close.** `B15`+`B16` conditional on the sign of
  `B10`…`B14` cumulative: does the morning's direction carry into the auction?
- **S3 — the shorted join.** Short-interest quintile (frozen v3 shorts, lagged by
  `panel.PUBLICATION_LAG_DAYS`, so knowable at the time) × `B16`: do the most-shorted
  names see different closing-auction pressure than the least? This is the one test
  only the shorted data enables, and it is the bridge back to the V304 mechanism.

## 6. What is NOT in scope

- No strategy node, no engine change, no `projects/asx.yaml` change. Nothing here
  trades and nothing here sizes.
- No k. V304 §4(1) still needs a real fill; this version has none.
- No claim on any window shorter than the two-half split; the 60-day 5m corpus
  audits bar structure and draws the volume profile, nothing else.

## 7. Artifacts

- `data/frozen_series/asx/intraday/1h/{CODE}.json.gz` + `MANIFEST.json` — committed
  (the study substrate; ~118 files).
- `data/frozen_series/asx/intraday/5m/` — frozen locally, md5s in the manifest,
  **not committed** (60-day rolling audit corpus, `.gitignore`d).
- `data/asx_runs/v307_tod.json` — the map: per-bucket mean/t/n, halves, F1–F3,
  S1–S3, volume profile.
- `scripts/v307_freeze_asx_intraday.py`, `scripts/v307_asx_tod.py`,
  `omega/nodes/asx/intraday.py`, `tests/test_asx_intraday.py`.

---

## 8. Results

_(blank at pre-registration)_

## 9. Verdict

_(blank at pre-registration)_

## 10. Next

_(blank at pre-registration)_
