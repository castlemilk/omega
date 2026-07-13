# V257 — On-chain Data-Acquisition Execution Runbook (OPERATOR)

**Date:** 2026-07-14 · **Author:** claude (Opus 4.8) · **Type:** operator runbook (no strategy code)
**Companion to:** [`V257.md`](V257.md) (pre-registration + falsifiers) ·
[`V256.md`](V256.md) (the flow-primary bet this data unblocks) ·
[`V254_ALT_DATA_SCOPING.md`](V254_ALT_DATA_SCOPING.md) Track C

> This is the **executable expansion** of the V257 pre-registration. Every step runs
> **on the live host**, by the user, with HTTPS egress. This document does not execute
> any of them — it is a checklist. Coin Metrics **community** tier needs **no API key**,
> only outbound HTTPS to `community-api.coinmetrics.io`.
>
> **The single gate at the end:** V256 reopens as buildable **iff** ≥ 3 of the 4
> pre-declared V256 signals land with ≥ 3-year daily coverage and byte-identical
> re-freeze MD5 (V257 falsifier). Do not re-register V256 until Step 4's checklist is
> all ✅.

## Conventions used below

- `REPO=~/projects/omega` (adjust to the host's checkout path).
- Freeze output root: `data/frozen_series/on_chain/` (mirrors the existing
  `data/frozen_series/` feeds — funding, OI, GDELT, FRED).
- All commands assume `cd $REPO` and the repo's Python (3.11+, `psycopg`+stdlib only;
  the freeze needs `urllib`/`json` from stdlib — no heavy deps).
- **Frozen-cache discipline (V238/V240/V257):** one network pull → files only on
  replay; canonical JSON (sorted keys, fixed float precision) → stable MD5;
  `PYTHONHASHSEED`-independent output.

---

## Step 1 — Verify Coin Metrics community access (no key)

**What it's for.** Confirm outbound HTTPS reaches the community API and returns the
documented schema *before* attempting a multi-year freeze.

**Precondition.** Outbound HTTPS (443) to `community-api.coinmetrics.io` is allowed
(egress firewall / proxy permitting). No key, no account.

**Command (one-date BTC hash-rate smoke — the lightest possible query):**

```bash
curl -sS --fail-with-body \
  'https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics=HashRate&start_time=2024-01-01&end_time=2024-01-01&frequency=1d&pretty=true'
```

**Expected output (schema):**

```json
{
  "data": [
    {
      "asset": "btc",
      "time": "2024-01-01T00:00:00.000000000Z",
      "HashRate": "5.4...e+08"
    }
  ]
}
```

Key fields: top-level `data` is an array of `{asset, time, <MetricName>}` objects;
values are **strings** (decimal), times are RFC-3339 nanosecond-precision UTC. A
multi-row query also returns `next_page_token` + `next_page_url` (cursor pagination —
the freeze script must follow it).

**Verify.** HTTP 200, `data[0].HashRate` is a non-empty numeric string.

**Common failure modes:**

| Symptom | Cause | Fix |
|---|---|---|
| `curl: (6) Could not resolve host` | DNS blocked/misconfigured | check resolver / allow `community-api.coinmetrics.io` |
| `curl: (35/60) TLS`/cert error | egress proxy MITM or stale CA bundle | update `ca-certificates`; set `CURL_CA_BUNDLE` if behind a corporate proxy |
| HTTP 403 `{"error":...}` | metric/asset not in **community** tier | it's a paid metric — see Step 2's catalog check; not a network fault |
| HTTP 429 | rate limit (community ≈ 10 req/6s, 3000/day soft) | back off; the freeze script paginates with a sleep between pages |
| HTTP 400 `bad_request` | malformed `metrics`/date | check exact metric casing (`AdrActCnt`, not `adractcnt`) |

---

## Step 2 — Signal-to-metric mapping + per-metric community-availability check

Per V256's 4 pre-declared signals, the Coin Metrics metric names (daily `frequency=1d`):

| V256 signal | CM metric name | Meaning | Freq | Community tier? |
|---|---|---|---|---|
| #1 net exchange netflow | `FlowInBTC` + `FlowOutBTC` (ETH: `FlowInETH`/`FlowOutETH`, or `*USD` variants) | on/off-exchange native-unit flow; netflow = in − out | 1d | **⚠️ often paid** — verify (Step 2b) |
| #2 active-address velocity | `AdrActCnt` | count of distinct active addresses/day (velocity = builder differences/normalizes) | 1d | ✅ community |
| #3 whale-cluster movement | `SplyAct1yr` | supply active in the last 1yr (holder-behavior proxy) | 1d | ✅ community (proxy; true whale cohorts are Glassnode/Santiment-tier) |
| #4 transaction volume | `TxTfrValNtv` | native-unit transferred value/day (network usage) | 1d | ✅ community |

> **Naming note.** The V256 pre-reg lists signal #4 as `stablecoin_supply` (per-chain)
> and calls `TxTfrValNtv` a "supporting" series. Coin Metrics community does **not**
> carry per-chain stablecoin supply for BTC (BTC has no native stablecoin); the honest
> CM-community 4-tuple for the BTC/ETH MVP is **{netflow, AdrActCnt, TxTfrValNtv,
> SplyAct1yr}**. Freeze all four available metrics; the V256 signal builder selects the
> ≥3 that clear the falsifier. Document whichever 4 you actually freeze in the manifest.

**Step 2b — confirm exactly which metrics are community-available (do this before freezing).**
The catalog endpoint reports the community-tier metric list; grep it for each name:

```bash
for M in FlowInBTC FlowOutBTC AdrActCnt TxTfrValNtv SplyAct1yr; do
  code=$(curl -sS -o /dev/null -w '%{http_code}' \
    "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics=$M&start_time=2024-01-01&end_time=2024-01-01&frequency=1d")
  echo "$M -> HTTP $code"   # 200 = available; 403 = paid tier
done
```

**Expected.** `AdrActCnt`, `TxTfrValNtv`, `SplyAct1yr` → 200. `FlowInBTC`/`FlowOutBTC`
may be 403 (paid). **A 403 on the flow metrics does NOT fail V257** — the falsifier's
3-of-4 gate anticipates exactly this (whale/flow may be paid-tier). Record which
metrics returned 200; those are the freeze set.

---

## Step 3 — Run the freeze pipeline

> **The freeze script `scripts/v257_freeze_on_chain.py` is authored as part of V257
> (see V257.md deliverable #2).** If it is not yet on the host's checkout, that is the
> V257 build task — this runbook covers running it, not writing it. It mirrors
> `scripts/v238_freeze_series.py` / `scripts/v240_freeze_gdelt.py` (one network pull,
> canonical JSON, MD5-checked, manifest-updating).

**Command:**

```bash
cd $REPO
python3 scripts/v257_freeze_on_chain.py \
  --symbols BTC,ETH \
  --metrics AdrActCnt,TxTfrValNtv,SplyAct1yr,FlowInBTC,FlowOutBTC \
  --start 2020-01-01 --end 2026-07-14 \
  --out data/frozen_series/on_chain/
```

(Drop any metric Step 2b returned 403 for — pass only the community-available set.)

**Expected runtime.** ~30 min for 2 assets × ~5 metrics × ~6.5 years daily
(~2,400 rows/series, paginated ~100–1000 rows/page with a rate-limit sleep). It is
network-bound, not CPU-bound.

**Expected output (per metric, per asset):**

```
data/frozen_series/on_chain/BTC/active_addresses.json
data/frozen_series/on_chain/BTC/transaction_volume.json
data/frozen_series/on_chain/BTC/supply_active_1yr.json
data/frozen_series/on_chain/BTC/net_exchange_netflow.json   # only if flow metrics available
data/frozen_series/on_chain/ETH/... (same set)
data/frozen_series/on_chain/MANIFEST.json                    # model/source + per-file MD5
```

Each series file matches the frozen-series schema:
`{name, source:"coinmetrics-community", fetched_at_utc, frequency:"daily",
first_date, last_date, n_obs, unit, series:{date→value}}`.

**Byte-identity check (re-run must produce identical MD5):**

```bash
# snapshot MD5s, re-run the freeze into a scratch dir, diff MD5s
find data/frozen_series/on_chain -name '*.json' ! -name MANIFEST.json \
  | sort | xargs md5sum > /tmp/v257_md5_run1.txt
python3 scripts/v257_freeze_on_chain.py --symbols BTC,ETH \
  --metrics AdrActCnt,TxTfrValNtv,SplyAct1yr \
  --start 2020-01-01 --end 2026-07-14 --out /tmp/v257_refreeze/
find /tmp/v257_refreeze -name '*.json' ! -name MANIFEST.json \
  | sort | xargs md5sum | sed 's#/tmp/v257_refreeze#data/frozen_series/on_chain#' \
  > /tmp/v257_md5_run2.txt
diff /tmp/v257_md5_run1.txt /tmp/v257_md5_run2.txt && echo "MD5 BYTE-IDENTICAL ✅" \
  || echo "MD5 MISMATCH ❌ — source non-reproducible, V257 FALSIFIER #2 fires"
```

**Verify.** `diff` is empty (identical MD5). A mismatch means the source back-revised
or the serialization isn't canonical → V257 falsifier #2 (non-reproducibility) fires;
do not proceed to V256.

---

## Step 4 — Verification checklist (V257 falsifier gate)

Run all of these; **all must pass** (mod the documented flow-tier exception):

```bash
python3 - <<'PY'
import json, glob, datetime as dt
from pathlib import Path
root = Path("data/frozen_series/on_chain")
files = [f for f in glob.glob(str(root/"**/*.json"), recursive=True)
         if not f.endswith("MANIFEST.json")]
assets = {"BTC","ETH"}
ok = True
per_asset = {a: [] for a in assets}
for f in files:
    s = json.loads(Path(f).read_text())
    a = Path(f).parent.name
    per_asset.setdefault(a, []).append(Path(f).stem)
    d0 = dt.date.fromisoformat(s["first_date"]); d1 = dt.date.fromisoformat(s["last_date"])
    yrs = (d1 - d0).days / 365.25
    # gap check: n_obs should be within ~2% of calendar days for a daily series
    cal_days = (d1 - d0).days + 1
    gap_frac = 1 - s["n_obs"] / cal_days
    status = "OK"
    if yrs < 3.0:            status = f"FAIL <3yr ({yrs:.1f})"; ok = False
    if s["frequency"] != "daily": status = f"FAIL freq={s['frequency']}"; ok = False
    if gap_frac > 0.02:     status = f"WARN gaps {gap_frac:.1%}"
    print(f"{a:4} {Path(f).stem:24} {s['n_obs']:5}obs {yrs:4.1f}yr gaps={gap_frac:5.1%} {status}")
for a in sorted(assets):
    n = len(per_asset.get(a, []))
    print(f"{a}: {n} metrics frozen ({'>=3 OK' if n>=3 else 'FAIL <3 signals'})")
    if n < 3: ok = False
print("OVERALL:", "PASS ✅ — V256 reopens" if ok else "FAIL ❌ — see rows above")
PY
```

Checklist items enforced above:
1. **File count** = `N_metrics × N_assets` (≥ 3 metrics × 2 assets = ≥ 6 files).
2. **Coverage** — each series ≥ **3-year** span (V257 falsifier #1).
3. **Cadence** — `frequency == "daily"`; gap fraction < 2% of calendar days (documented
   if a metric legitimately has a shorter/irregular history, e.g. ETH pre-2016).
4. **MD5 checksums** — stored in `MANIFEST.json` and re-verified in Step 3.

---

## Step 5 — What happens after a successful freeze

Once Step 4 prints `PASS ✅`:

1. **V256 re-registers as buildable.** Edit [`V256.md`](V256.md) status from
   `PAUSED — data-blocked at Phase 0` to `buildable`, citing the frozen metric set.
2. **V256 Phase 0 audit re-runs.** The audit that previously found "only a market-wide
   stablecoin aggregate on disk" now enumerates `data/frozen_series/on_chain/` and
   should report **≥ 3 of 4** signals present (per-asset, ≥3yr, reproducible).
3. **Full V256 offline scorer + verdict follows** — flow-primary composite over the
   available signals, cross-sectional across {BTC, ETH}, walk-forwarded and gated
   **exactly as the V256 pre-registration specifies** (no post-hoc redesign to fit the
   data that arrived — the signal set is whatever V257 delivered; the strategy shape
   and gates are pre-committed).

**If Step 4 FAILs** (< 3 signals, < 3yr, or MD5 mismatch): V256 stays PAUSED. The
options are (a) provision a paid tier (Glassnode/CryptoQuant per V257.md source table)
to widen coverage / add true exchange-netflow + whale cohorts, or (b) accept the CM
community MVP is insufficient and re-scope V256's signal set. Either is a new
pre-registration, not a silent redesign.

---

## Scope guardrails (this runbook)

- Running the freeze writes **only** new frozen-series files + updates the on-chain
  manifest. It touches **no** strategy code (`strategy.py`, `signal_generation.py`,
  Victoria state) and no live-broker.
- Community tier is free; only escalate to a paid source after the MVP clears the V256
  falsifier on BTC/ETH — do not buy a tier on hope (V257.md rationale).
