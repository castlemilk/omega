# Victoria rendering handover — charts, analytics, and signals in the Foreman shell

How to add or change anything visual in this plugin so it stays fast, honest,
and native to the harness. Written 2026-08-21 after the shell's first full
build-out and live drive; every rule below traces to a defect that actually
happened or a constraint that actually bit.

## 1. The rendering stack, bottom to top

```
geometry.ts      pure math: scales, paths, tick arrays, bucket colors.
                 NO React, NO DOM. Unit-tested with EXACT expected values.
charts.tsx       bespoke SVG components consuming geometry outputs.
format.ts        trading-specific formatters (signedUsd, pct, regimeColor,
                 pluralize). Generic time/status helpers come from the kit.
hooks.ts         data fetching per view (useVictoria*). Loading/error/empty
                 tri-state. All IO through client.ts.
client.ts        the ONLY place wire shapes are known. Typed against the
                 proto/handler with a provenance comment per type.
views/*.tsx      one file per tab. Composition + copy. No fetch, no math.
```

The layering is enforced socially here and structurally at the boundary: the
omega-side `imports.test.ts` fails any shell file importing anything besides
`react`, `@omega-harness/usecase-kit[/ui]`, or a relative path — node builtins
included. Keep math out of views and IO out of charts and the guard stays
quiet.

## 2. Charts: the house idiom (why there is no chart library)

The harness renders everything with thin-stroke bespoke SVG on the dark token
set (`PulseSparkline` in the host is the ur-example). Victoria follows it:

- **Geometry is a pure function first.** Every chart starts as
  `geometry.ts` functions returning numbers/paths/arrays. The chart component
  is a dumb projection of that output into SVG. This is what makes the
  house testing rule ("assert values, not shapes") possible: tests pin exact
  path strings, exact tick arrays, exact rgba buckets.
- **Tokens, not colors.** Stroke/fill/text classes come from the harness
  Tailwind set (`ok/warn/danger/accent`, the ink→ghost text ramp, `line`
  hairlines — note `line` is a *borderColor* token: `border-line` works,
  `bg-line` silently generates nothing). Numerals are JetBrains Mono
  (`font-mono`). The use-case accent is available as `var(--uc-accent)`.
- **Domain colors have one home**: `format.ts` (`regimeColor` maps
  crisis/high_vol/normal onto danger/warn/ok). Never inline a regime color in
  a view.
- **Existing components to extend, not duplicate**: the equity line chart
  (axis ticks, benchmark overlay, the `train_end` IS/OOS vertical marker),
  the funnel (stepped drops with labeled reasons), grouped bars (conviction
  histograms A/B), and the correlation heat grid (colored table cells — a
  table, not a canvas, on purpose: it inherits text rendering, selection,
  and accessibility for free).

### Adding a new chart, the checklist

1. Write the geometry function + exact-value tests (include the degenerate
   inputs: empty series, single point, all-equal values, NaN-free guarantee).
2. Build the SVG component in `charts.tsx` in the idiom above. ViewBox-based;
   no fixed pixel widths (the drive found a clipped funnel label — `padBottom`
   exists because of it).
3. Feed it from a hook, never fetch inside it.
4. Empty/error states per §4 — a chart with no data renders the *reason*,
   not an empty axis. Zero-filled sparklines that look like data are the
   named failure of the old Live view; don't reintroduce them.

## 3. Data contracts feeding the visuals

Three transports, one rule: **client.ts owns the wire; hooks own the
tri-state; views own the copy.**

| Source | Transport | The trap |
| --- | --- | --- |
| `VictoriaService` (9 RPCs: portfolio, positions, PnL, signals, signal history, trades, backtest, equity curve, risk) | Connect-JSON `POST /omega.v1.VictoriaService/<Method>` | **camelCase and omit-zero.** Proto3 elides zero-valued fields: an empty DB answers `{}` — and once answered literally `{"compositeDirection":"SHORT"}` because the direction survived while the zero score vanished. Absent means *absent*, renders as `—`, and a directional/derived field is only shown when there is evidence its inputs were computed. |
| Training REST (`/api/v1/training/{versions,compare,gates,forensics,log,decision-traces,trade-details,metrics}`, `/api/v1/signals/correlation`, `/api/v1/training/grid-ruler`) | plain GET | Shapes come from `internal/handler/training_handler.go`, which normalizes files under omega's `data/`. Version labels are arbitrary cell strings (`v252_replay_2025-03-05`), case-sensitive on the wire, and the journal (V-uppercase) and gate files (v-lowercase) are **different namespaces** — normalize case at jump sites and never assume `v\d+`. |
| Training SSE (`/api/v1/training/events/stream`) | EventSource | **Named events** (`connected`, `progress`) — the kit's `sse()` needs its `events:` option or you receive nothing. |

Operational facts the visuals depend on:

- The API's CORS allowlist contains `http://localhost:5173` only. Moving the
  web port breaks fetches silently-ish; moving the API needs BOTH
  `OMEGA_API_PORT` (server) and `VITE_UC_VICTORIA_URL` (client) — setting one
  without the other looks identical to a dead API. `task doctor` probes the
  resolved URL and says which.
- Gate/ruler JSON carries a first-class `verdict` vocabulary
  (`PASS/FAIL/NO_OP/NO_BASELINE/NOT_EVALUATED/ERROR` per-cell;
  `PASS/FAIL/INSUFFICIENT_GRID/ERROR` for the grid ruler). Render every
  member; an unknown-to-you verdict renders as "not reported", never green.
  `ruler_notes` is always `[]`-not-null — every conservative scoring choice
  lives there and should be surfaced.

## 4. The honesty rules (the shell's actual design system)

These outrank visual polish, and each has a live-drive scar attached:

1. **Empty states say WHY and name the source** that would fill them ("the
   victoria_trades table has no rows"; the correlation empty state names the
   exact `/tmp/{version}_signal_correlation.json` path). "No data" alone is a
   defect.
2. **Errors render verbatim, bounded.** `DataSourceError` carries status + a
   body excerpt; show it (the `/progress` 500 was rendered on screen for two
   days and that was correct — it was a real backend bug).
3. **Never derive a fact from absence.** The `SHORT`-from-nothing tile is the
   canonical violation.
4. **Stale is not live.** If a payload's own metadata says it isn't current
   (mtime-inferred status, incoherent totals like `45 / 0`), render an idle
   state that says what the numbers actually are ("database aggregates —
   real, and not live").
5. **Disclose data quirks instead of smoothing them** — the archived
   v48/v49 placeholder labels, the duplicate `v10` cell, run_diff.py's
   hardcoded keys, the "gated against itself" files all render with one-line
   explanations. A reader who spots a quirk you hid stops trusting the views
   you didn't.
6. **Big lists cap with a count** ("Show all 450 runs"), never silently
   truncate; columns that have never held a value say so ("not computed")
   rather than being dropped.

## 5. Testing and verification conventions

- Vitest runs in **node environment, no jsdom** (deliberate). Views are
  tested with `renderToStaticMarkup` asserting operator-visible text; handler
  wiring is invoked directly. Browser event dispatch is covered by live
  drives, not unit tests — say so in the test when that's the split.
- Geometry: exact values (the house rule exists because an
  `expect.any(Number)` suite once let a 75% under-report pass in the host).
- Fixtures are **captured from real payloads** and cite their source file in
  a comment. When the wire and the docs disagree, the wire wins and the
  divergence is noted.
- `make foreman-plugins-check` from omega's root rebuilds the kit (dist-skew
  guard), typechecks, and runs the suite. The kit resolves through `dist/` —
  editing kit `src/` does nothing for consumers until rebuilt.
- Big changes end with a **live drive**: boot per FOREMAN.md, walk the views
  against the real API, read actual numbers off the screen, screenshot, and
  keep a friction list. Every high-value defect this shell has had was found
  by a drive, not a suite.

## 6. Out-of-tree constraints (the plugin lives here, renders there)

- **Tailwind purge**: the harness scans this directory via the discovery
  config's content globs. A class string must appear literally in scanned
  source — computed class names get purged. New kit-level primitives need the
  kit's `src/` in the glob (it is; don't regress it).
- **One React, one kit**: the harness pins `resolve.alias` for both kit
  entries and dedupes react. Never add a direct react-dom/react dependency
  edge that bypasses it; never import the kit by relative path.
- **Env in prebuilt code**: `import.meta.env` is not rewritten inside the
  kit — env reaches data sources through the injected env bag
  (`setUseCaseEnv` in the host). Don't read `import.meta.env` in plugin code.
- **HMR**: editing files here hot-reloads in the harness dev server via
  `registerRoster` replace-by-provenance. A duplicate-id throw on reload
  means someone re-registered outside the roster.
- **Adding a view is a two-repo act** by design: the view here, plus its row
  in the harness's `roster.test.ts` (the host asserts exactly what it
  renders). The README states this; budget for it.

## 7. Where to extend next (ranked, with the data already available)

1. **Regime timeline** — crisis/high_vol/normal bands over cycles with
   per-regime PnL; data already in trades CSVs (`regime` column) and
   decision traces. Geometry: banded strip + per-band aggregates.
2. **Conviction threshold bands** — the funnel shows counts; the next level
   plots composite vs the regime-adaptive buy/sell thresholds per ticker
   (decision snapshots carry `conviction_threshold_buy/sell`, `_thresh_scale`).
3. **Signal health board** — per-signal IC/weight/decay from
   `signal_performance` (`GetSignalPerformance`) + the correlation grid you
   already render; the seeded ICs in `data/signal_ic_history.json` give a
   real corpus.
4. **Equity drawdown shading** — the chart has the `train_end` marker; add
   the underwater band (geometry-first, exact-value tests on the band path).
5. **Campaign-ruler card, populated** — renders today only when a
   `*_grid_verdict.json` exists; the first real walk-forward grid run makes
   it live. Until then the Gates copy references it conditionally.
6. **Per-cycle metrics** — `/tmp/{version}_metrics.jsonl` is ephemeral; if a
   durable home lands (e.g. copied into `data/` at run end), the Live view's
   sparklines get real series. Don't build against `/tmp`.

## 8. Pointers

- Authoring the shell itself: `harness/docs/USE-CASE-SHELLS.md` (contract,
  discovery, health, the six-field guest rule).
- Boot + operations: `harness/docs/FOREMAN.md` (three-command start, doctor,
  Victoria live data, `OMEGA_API_PORT`/`VITE_UC_VICTORIA_URL`).
- Backend shapes: `internal/handler/training_handler.go`,
  `proto/omega/v1/victoria.proto`, `omega/eval/{standing_gates,grid_ruler}.py`.
- The drive reports that produced §4's rules live in the session history;
  their screenshot conventions (`/tmp/*-shots/`) are worth keeping for every
  future drive.
