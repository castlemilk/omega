# V309 — The forward ASX lane: one honest observation a week, no broker, no claim

**Date:** 2026-09-13
**Status:** PRE-REGISTERED — infrastructure (the V250–V252 shape), smoke-tested, not a mechanism. Results blank below until the cycle has run.
**Parent:** V308 (which re-scoped this from "paper book" to "forward record of the spread")

---

## 1. What this is, and what it is not

The ASX line's one surviving fact is a **cross-sectional spread**: least-shorted
names beat most-shorted names, +0.298%/wk at t = +2.85 over 590 weekly periods
(V303), replicated out of sample. Everything built *on* it — the long-only book,
the capacity tables — has now failed an honest comparator (V308). And every
observation behind the spread is historical, frozen, and has been looked at many
times.

This version builds the thing the campaign has said since V249 is the only
un-Goodhartable evidence: **a forward record**. Each day after the ASX close, a
daemon appends to an append-only store what the market published — the ASIC
short panel, daily prices, the 1h bars for the V307 universe — and each week it
writes down the realised Q1−Q5 spread and Q1's excess over the equal-weight
eligible universe, **with the comparator's definition inside the record**.

It is **not** a paper book. It carries no capital, no equity curve, no PnL claim;
the runner's equity field is a constant and says so. It places no orders and
talks to no broker. The standing guardrail is absolute.

## 2. Why the shape is the V252 shape

`omega.live_paper` already owns a drift-free daily UTC scheduler, an atomic
checksummed checkpoint, and a runner that composes them around a cycle function
and survives kill/restart (V252 Test B: byte-identical resume). A project node may
import the platform; the ASX lane is a `cycle_fn` and nothing else. Reusing it
means the crash-safety this lane inherits was proven in the real V253 deployment,
not just in a test.

## 3. Cycle (pre-declared)

Tick **09:00 UTC** daily (19:00/20:00 Sydney; the close is 06:10 UTC and ASIC's
T+4 report lands mid-morning Sydney). Per cycle, in order:

1. **Short panel.** `GetAvailableDates` → every date not yet in the store is
   fetched with `GetMarketByDate {limit: 1000}` and written **once** (a stored
   date is never rewritten — ASIC positions are revisable, so `fetched_at` is
   provenance and a re-fetch would be a different observation). Token: the OAuth
   refresh token in `~/.config/omega` renews headlessly (measured 2026-09-13,
   60-minute access tokens); on failure the anonymous tier is used and the
   record says which. Bounded to the API's 90-date window.
2. **Daily prices.** One batched yfinance `1d` pull for the panel's codes
   (~740, ~40 s measured); each new session written once as
   `prices/{session}.json`. First cycle uses a one-month window to close the
   gap between the frozen v3 substrate (ends 2026-09-02) and today.
3. **1h bars** for the V307 universe (119 names), same write-once rule,
   `intraday_1h/{session}.json`.
4. **Weekly mark.** Sessions are grouped by ISO week; when a week is complete
   (its last session is a Friday, or a later week's session exists), the book
   formed at the *previous* week's last session is realised over this week:
   - panel used = latest panel date ≤ formed date − `PUBLICATION_LAG_DAYS` (7),
     exactly `panel.knowable_short`'s rule;
   - eligible = price ≥ $0.20 and ADV20 ≥ $500k at the formed date, ADV from v3
     history overlaid with the forward store (V304/V308 screens, unchanged);
   - Q1 = least-shorted fifth, Q5 = most-shorted fifth, equal-weight;
   - a name without a price at either end is excluded (V303), and the count is
     in the record;
   - the record carries `spread_q1_q5`, `excess_q1_vs_ew`, the three group
     returns and sizes, the panel date, the lag, and a `comparator` string.
5. Checkpoint, then one runner log line. Equity constant; `extra_log` carries
   the mark when one was written.

Prices are yfinance's, not the API's. That is a deliberate second source: the
frozen v3 prices are the API's (#582-despiked), and a forward spread computed on
an independent price feed is a check on both.

## 4. Falsifiers (pre-declared)

- **F1 — a real cycle completes.** Run once, now, against today's data: the
  three stores are written with a manifest, and the counts (panel dates,
  price sessions, 1h sessions) are reported. A partial write is a FAIL.
- **F2 — idempotent restart.** Running the cycle function a second time the
  same day writes **nothing**: every store md5 unchanged, manifest byte-identical,
  no duplicate mark. (V252's Test B, at the store level.)
- **F3 — the mark function agrees with history.** The same `weekly_mark` code,
  run over the frozen v3 substrate and the committed 91-date short panel for
  every complete week it can (May → Aug 2026), returns a series whose **mean and
  sign are reported** next to V303's +0.298%/wk. This is a reconciliation of the
  *instrument*, not a re-test of the spread: at ~15 weeks it cannot adjudicate
  anything, and no bar is set on the value.
- **F4 — supervised.** A launchd agent (`com.omega.asx_forward`) is loaded, the
  daemon is alive under it, and its first tick writes a checkpoint. Verified by
  reading the checkpoint and the log, not by trusting `launchctl`.

## 5. What accrues, and the resume criterion

One spread observation per week, ~52 per year. Pre-declared: **at 52 forward
weeks**, the forward series is tested once — mean spread > 0 at t ≥ 2.0 — and
only then is a long-*short* version pre-registered, with borrow priced
explicitly (V289 §7 ruled shorting out for a retail account; the forward record
is what would justify revisiting that). Until then the lane records and claims
nothing.

## 6. Artifacts

- `omega/nodes/asx/forward.py` — store, panel/price/bar documents, the mark.
- `scripts/asx_forward_daemon.py` — the cycle function composed on
  `omega.live_paper`; `--once` for F1/F2, `--reconcile-v3` for F3.
- `scripts/asx_forward_launchd.sh` + `~/Library/LaunchAgents/com.omega.asx_forward.plist`.
- `tests/test_asx_forward.py` — write-once, lag rule, quintiles, gap exclusion,
  week completion.
- Store root `data/asx_forward/` (gitignored), overridable by `OMEGA_ASX_FORWARD_DIR`.

---

## 7. Results

_(blank at pre-registration)_

## 8. Verdict

_(blank at pre-registration)_
