# V307 — ASX intraday: does the trading day have a recurring shape, and is any of it worth a trade?

**Date:** 2026-09-13
**Status:** COMPLETE — Phase 0 audit + 1h freeze + time-of-day map. Pre-registered at commit `9e96e99b` before any code; §8–§10 filled after the run. F1 PASS, F2 0/8, F3 0/8, S1 significant and audited.
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

**Corpus.** 119 names at 1h (120 − NSR), 2023-10-26 → 2026-09-11, downloaded
2026-09-13; ~86k name-sessions; 357 frozen files, `--verify` BYTE-IDENTITY PASS.
Six holes recorded in the manifest (NSR ×3 no data; CTD partial at 1h and 5m;
SGR partial at 5m).

**F1 — PASS.** Complete-session share 97.9% (bar 97%); 0 off-stamp bars; 0 NaN
closes; the 16:00 bar's median share of session volume 34.1% (bar 15%) — it is the
auction.

**One defect, found by reading the metadata (V302), and it is the source's, not
mine.** The 10:00 bar's volume is **0 on 70.3% of 1h sessions and 98.1% of 5m
sessions** (the 1h 16:00 bar: 23%). The *prices* on those bars are real —
open == close on only 4.1% of them, open == previous close on 7.4%, and the
first-hour return has the same sign on the zero-volume and non-zero subsets
(−3.1 vs −1.5 bps). yfinance simply does not carry the opening auction's volume.
Consequence: the 10:00 cell of the 1h volume profile is **unmeasurable** (reported
as such, not averaged in), and the map's hourly volume shares are taken from the
5m corpus, which loses only the opening five minutes.

### 8.1 The map — eight buckets, EW daily series, n ≈ 723–728 sessions

| bucket | n | mean bps | t | H1 bps (t) | H2 bps (t) | F2 | F3 |
|---|---:|---:|---:|---:|---:|---|---|
| `ON` overnight | 723 | **+6.53** | +2.50 | +8.15 (+2.26) | +5.41 (+1.48) | no | no |
| `B10` first hour | 728 | −2.64 | −2.40 | −1.91 (−1.26) | −3.15 (−2.05) | no | no |
| `B11` pre-lunch | 728 | +0.73 | +0.80 | −0.27 (−0.22) | +1.42 (+1.11) | no | no |
| `B12` lunch | 728 | −0.64 | −1.00 | +1.10 (+1.19) | −1.85 (−2.16) | no | no |
| `B13` | 728 | −0.59 | −1.11 | −0.77 (−0.99) | −0.46 (−0.64) | no | no |
| `B14` | 726 | −0.42 | −0.82 | −0.75 (−0.85) | −0.19 (−0.31) | no | no |
| `B15` last hour | 723 | +1.44 | **+3.07** | +0.11 (+0.16) | +2.37 (+3.88) | no | no |
| `B16` auction | 723 | +1.72 | +1.57 | +2.96 (+1.14) | +0.85 (+2.36) | no | no |

**F2 — no bucket is a recurring pattern.** The only |t| ≥ 3 is `B15`, and all of it
is the second year (H1 t = +0.16): a one-year effect, not a recurring one. `ON` is
the largest drift (+6.5 bps) and sits at t = +2.5 — under the bar, and an
overnight bucket is not an intraday trade in any case. Everything else is inside
±1.1.

**F3 — nothing clears 20 bps.** The largest hourly |mean| is 2.6 bps; the best
same-sign run of adjacent buckets is `B15`+`B16` at **+3.2 bps** cumulative. The
pre-declared expectation held: the trading day's *unconditional* shape is an order
of magnitude under retail cost, and under the 5 bps sensitivity too.

**The "pre-lunch" hour is empty.** `B11` +0.7 bps (t +0.8), `B12` −0.6, `B13` −0.6.
There is a lunch lull, but it is in *volume*, not returns — see the profile.

### 8.2 Secondaries

| | mean bps | t | n | bar |t| ≥ 2.4 |
|---|---:|---:|---:|---|
| **S1 gap reversal** — `B10` \| ON>0 minus `B10` \| ON<0 | **−15.62** | **−9.85** | 627 | **yes** |
| S2 momentum into close — (`B15`∘`B16`) \| morning>0 minus \| morning<0 | −1.09 | −0.48 | 721 | no |
| S3 shorted join — `B16` Q5 (most shorted) minus Q1 | +3.78 | +0.81 | 723 | no |

S3 by quintile (bps into the auction): Q1 +1.0, Q2 +0.8, Q3 +1.0, Q4 +0.4,
Q5 +4.8. The most-shorted quintile does print higher into the close, and at t = 0.8
that is nothing. 119 of 119 names had a short series; publication lag 7 days.

### 8.3 Volume profile (5m corpus, 119 names, 60 sessions; hour shares exclude the unmeasurable 10:00 five minutes)

| 10:00h | 11:00h | 12:00h | 13:00h | 14:00h | 15:00h | **16:00 auction** |
|---:|---:|---:|---:|---:|---:|---:|
| 8.1% | 7.0% | 6.0% | **5.2%** | 6.4% | 11.0% | **36.1%** |

The continuous-session trough is at **13:15**. Over a third of the ASX day prints
in one ten-minute auction, and 47% in the last hour plus the auction.

### 8.4 Post-hoc audits on S1 (not pre-registered; they change no verdict)

S1 was strong enough to need an artifact check. The obvious one: ASX opens in five
alphabetical groups from 10:00:00 (0–9, A–B) to 10:09:00 (S–Z), so if the
"reversal" were a stale pre-open price being corrected by the first real trade, it
would be weakest in the A–B group, whose 10:00 bar actually contains its auction
print.

| opening group | names | S1 bps | t | n days |
|---|---:|---:|---:|---:|
| A–B (opens 10:00:00) | 21 | −16.18 | −7.28 | 423 |
| C–F | 24 | −17.35 | −5.78 | 427 |
| G–M | 20 | −5.43 | −1.30 | 322 |
| N–R | 20 | −9.74 | −3.20 | 395 |
| S–Z (opens 10:09:00) | 34 | −20.62 | −7.70 | 526 |

Present, and strong, in the one group where it cannot be a stale price. Not an
artifact.

Then *where in the hour* it lives, on the 5m corpus (59 sessions), gap-up minus
gap-down cumulative return from the **10:00 open**:

| to 10:00 close | 10:05 | 10:10 | 10:15 | 10:30 | 11:00 | 12:00 | 16:10 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| −3.6 (t −1.4) | −11.5 (−4.0) | **−13.9 (−4.8)** | −12.9 | −14.8 | −14.7 (−3.0) | −8.7 | −16.2 (−2.6) |

**The whole reversal is realised within ten minutes of the open**, and then holds.
And from the **10:10 open** — the first price every group has actually traded at,
i.e. the first *tradeable* entry — the same conditional spread is −5.8 bps to 10:55
(t −1.75), −1.1 to 12:00, −10.1 to 16:10 (t −1.67). Not significant at n = 59,
and below the bar even taken at face value.

## 9. Verdict

**The ASX trading day has a shape, and none of it is a trade.**

- Eight buckets, **zero** recurring under F2, **zero** clearing 20 bps under F3.
  The largest hourly drift on liquid ASX names is under 3 bps. The verdict on
  trading the ASX from this data **does not move**: V304 stands.
- **The one real regularity is the opening auction overshooting.** Names that gap
  up at the auction underperform names that gap down by ~15 bps, at t ≈ −10 over
  627 sessions, in every opening group, and *all of it* accrues in the ten minutes
  after the print. That is a statement about who is on the other side of the
  auction: the return belongs to whoever provides liquidity *into* the open — a
  market-maker's trade — and by the time a continuous-market order can fill it is
  −5.8 bps and inside noise. At 20 bps round trip it is dead. At the 5 bps
  sensitivity it is ~7.8 bps per leg gross, needs shorting half the book, and
  needs auction participation on the wrong side of a 54 bps median gap. This is
  the V304 shape again, at a different clock: **real where it cannot be traded**.
- **"Pre-lunch" is empty.** The lull is in volume (trough 13:15, 5.2% share for the
  13:00 hour), not in returns.
- **The shorted join is null at this resolution.** Short interest does not
  predict the closing auction on liquid names (t +0.8).

What the map IS worth — §1's framing 2: **36% of the day's volume prints in the
closing auction and 47% in the final hour.** V304's capacity table charged impact
against full-day ADV, which is an implicit assumption about *how* a rebalance is
executed. The profile turns that into a number: an auction-only print has 0.36×
the day's liquidity behind it, a last-hour VWAP 0.47×. Whether the quarterly book
that survived costs in V304 does better or worse under a stated execution schedule
is now a computation on frozen data, not a guess.

Caveats carried forward, stated once: two calendar years, one regime (no bear
market in the window); a liquid-large-cap universe chosen point-in-time; the
opening five minutes' volume is not observable from this source at all.

## 10. Next

**Plainly: nothing in V286→V307 supports daily trading of the ASX.** The only
configuration with a positive net number is quarterly, whole-universe, and it is
+4%/yr at t = 1.8 (V304 §1). What changes that is unchanged from V304 §4 — a
measured k from real fills, or a cheaper way to hold the exposure — and this
version has moved only the second.

- **V308 candidate — execution-schedule re-pricing of V304's quarterly book.**
  Recompute the V304 capacity table under two declared execution schedules
  (closing-auction print; last-hour + auction) using the V307 liquidity shares as
  the participation base, with k still unmeasured and swept. Pure re-computation on
  frozen data; no new alpha claimed. Pre-register the bar before running it. This
  is the only thing the map feeds directly.
- **Not queued: more intraday buckets, lags or conditionings.** The unconditional
  map is flat and the one conditional regularity is a liquidity-provision return.
  Mining a flat map at finer resolution is the R2 pattern from the campaign
  retrospective — variance mining, not science.
- **The campaign decision, not a V###:** the honest path to *any* ASX trading is
  the V253 shape — a forward, daily, paper-only ASX lane that accrues
  un-Goodhartable observations at one per session. The intraday freeze built here
  is refreshable by design (`--force`) and would be that lane's substrate. That is
  a decision for the operator, and it is the one that would actually answer the
  question this version was asked.
