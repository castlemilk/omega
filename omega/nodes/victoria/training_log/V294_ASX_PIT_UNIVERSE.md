# V294 — The real universe, and the first ASX result that survives its own outliers

**Date:** 2026-09-02
**Status:** measured, suggestive, NOT significant
**Upstream:** shorted.com.au#579 + #581 (merged), #576 (shipped as #580), #582 (open)

## 1. The universe was never the API's fault

The engine had been running on 69 frozen survivors. `GetMarketByDate` has served a
genuine point-in-time universe since 2026-08-31 — it returns GXY (Galaxy
Resources, merged into Allkem in 2021) at 2020-04-06, and `totalCount` grows
553 → 703 → 740 across 2020/2021/2026.

| | before | after |
|---|---|---|
| codes | 69 survivors | **1,658 point-in-time** |
| priced | 55 | 1,006 |
| median cross-section | **9–12** | **776** |

Membership comes from each name's own dated short series, so enumeration costs 34
requests rather than 1,900. 652 codes (39%) have no upstream price history — the
survivorship hole, quantified rather than assumed (#576, since shipped as a
`has_price_history` flag).

## 2. Getting there needed auth, and auth needed a fix

Anonymous is 30/min and 500/month against ~3,300 requests. The token was being
ignored: a `VISIBILITY_PUBLIC` method returned before the Authorization header was
read, so `extractIdentifierAndTier` keyed the caller `ip:<addr>`. **This was not
OAuth-specific** — a `/developer` API key was ignored on those methods too.

`ValidateIdentityToken` (#579) reads a token for IDENTITY on public methods while
`ValidateConnectToken` still refuses an MCP audience for AUTHORITY, so a read-only
MCP grant still cannot reach `MintToken`. #581 then added an internal tier grant
so an operator need not fake a Stripe subscription.

`scripts/shorted_oauth.py` does the whole flow — discovery, dynamic registration,
PKCE S256, loopback redirect, self-refreshing, cache outside the working tree. No
API key is pasted anywhere. Verified 30/min → 60 → 300.

## 3. Two more defects, and the seventh instance of the pattern

**Mine: the concentration cap never bound.** Capping to 8% then re-normalising to
fully-invested returns every position to its uncapped size. A six-name book summed
to 0.48, scaled back to 1.0, and every name sat at 16.7%. Fixed by iterating
cap → redistribute → cap; the book now stays under-invested rather than breaching.

**Upstream (#582): foreign-exchange prices for ASX tickers.** `ASX:AMD` (Arrow
Minerals, ~$0.02) prints **$214.99** — NASDAQ's AMD — for one session, then
reverts. `ASX:AXP` prints **$381.05**, which is NYSE American Express. **215 of
1,006 codes (21%)**, 745 of the jumps in Nov–Dec 2025.

Both were found the same way every defect in this campaign has been found: as a
number that looked like a result. That is the seventh consecutive version where
the bottleneck was the data, not the signal.

## 4. The filter, and why it keys on reversion

`ApiPriceSource._despike` drops a session that is >10x its neighbours **on both
sides**. The test is REVERSION, not magnitude, and the distinction is the whole
point: a share consolidation is also a >10x move, but it is a permanent level
shift — extreme against its predecessor, normal against its successor. Filtering
on magnitude alone would silently delete every legitimate consolidation.

374 spike sessions removed; codes still showing an implausible step fell 215 → 51.
Those 51 are sparse series with multi-year gaps, and are quarantined outright —
excluding a name can only remove return, never manufacture it.

FPH is NOT caught: its distortion is a sustained level shift, not an isolated
spike. A reversion test cannot see that, and this is recorded rather than papered
over.

## 5. The result

414 non-overlapping weeks, 2019-04-29 → 2026-08-28, 20bp round trip, vs XJT:

| | raw v3 | despiked + quarantined |
|---|---|---|
| mean excess | +0.201%/wk | **+0.253%/wk** |
| sd | 2.864% | 2.899% |
| **t** | 1.43 | **1.78** |
| excl top 3 | t = 0.68 | **t = 1.10** |
| top-3 share | 0.62 | 0.57 |
| worst week | −21.7% | −9.4% |
| H1 / H2 | 0.78 / 1.20 | 0.96 / 1.50 |

**t = 1.78 is not significance** and the result is not claimed as an edge.

What IS new: this is the first ASX run whose edge does not vanish when the best
three weeks are removed. Every prior version collapsed — V292 to t≈0, V293 to
−0.10. Here it drops to t = 1.10 and stays positive, both halves agree in sign,
and the loss tail more than halved. That is a different failure mode from the six
before it: previously the mean was an artifact of three weeks, and now it is not.

## 6. What would settle it

The best week is still +40.7%, which on a capped book means residual
contamination rather than a real move — #582 is open and the prices are not yet
correct at source. A trustworthy number needs the upstream fix and a refreeze, not
another filter of mine. Until then this is *suggestive and unproven*, which is a
better place than the campaign has been, and still not a result.
