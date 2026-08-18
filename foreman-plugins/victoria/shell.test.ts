/**
 * The Victoria shell, on its own terms.
 *
 * This repository has no harness in it, so what is asserted here is everything
 * the shell decides for itself: its manifest, and the pure logic its views are
 * built out of. The other half — that the harness's roster actually registers
 * this shell, and that its tabs land after the core six in the right order —
 * is asserted in the harness, against the generated roster
 * (`apps/web/src/foreman/usecases/roster.test.ts`). Neither side can assert the
 * other's half, and duplicating either would mean a test that passes against a
 * copy rather than against the thing that ships.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { victoriaUseCase } from './index.js';
import { predecessorOf, sortVersions } from './views/Runs.js';
import { summariseByRegime } from './views/Trades.js';
import { maxDrawdown } from './views/Equity.js';
import { failuresForGate, summariesIdentical, summaryRows, unclaimedFailures } from './views/Gates.js';
import {
  blockingBreakdown,
  cyclesOf,
  decisionCounts,
  funnelCounts,
  isProposal,
} from './views/Conviction.js';
import {
  histogramGroups,
  histogramRows,
  regimeRows,
  reportKeys,
  sideLabel,
  symbolDeltas,
} from './views/Forensics.js';
import { entryStatus, sortJournal } from './views/Journal.js';
import {
  getFocusVersion,
  resetFocusVersion,
  setFocusVersion,
  subscribeFocusVersion,
} from './store.js';
import { settleTrades, TRADE_DETAILS_SOURCE, TRADE_RPC_SOURCE } from './hooks.js';
import { DataSourceError } from '@omega-harness/usecase-kit';
import { pct, pnlClass, ratio, regimeColor, signedPct, signedUsd, usd } from './format.js';
import { GATE_NAMES, type VersionInfo } from './client.js';

describe('the manifest', () => {
  it('declares exactly one data source, the omega API', () => {
    expect(victoriaUseCase.dataSources).toHaveLength(1);
    expect(victoriaUseCase.dataSources?.[0].id).toBe('omega-api');
    expect(victoriaUseCase.dataSources?.[0].envVar).toBe('VITE_UC_VICTORIA_URL');
  });

  it('carries an accent that is legible on the canvas', () => {
    // victoria.yaml declares #00ff00; the shell brings it onto the palette.
    expect(victoriaUseCase.accent).toBe('#3fd97d');
    expect(victoriaUseCase.accent).not.toBe('#00ff00');
  });

  it('renames only the term that reads naturally', () => {
    expect(victoriaUseCase.vocabulary).toEqual({ harness: 'desk agent' });
  });

  it('namespaces every view id with the shell id, so no core tab is shadowed', () => {
    // The harness drops a view whose id collides with a core view rather than
    // letting a plugin make Console unreachable. Namespacing is how a shell
    // never finds out.
    expect(victoriaUseCase.views.map((v) => v.id)).toEqual([
      'victoria-overview',
      'victoria-runs',
      'victoria-live',
      'victoria-trades',
      'victoria-equity',
      'victoria-signals',
      'victoria-gates',
      'victoria-conviction',
      'victoria-forensics',
      'victoria-journal',
    ]);
    for (const view of victoriaUseCase.views) {
      expect(view.id.startsWith('victoria-')).toBe(true);
    }
  });
});

// The zero-requests guard lives in `./manifest-cost.test.ts`, not here: this
// file statically imports the manifest, so a dynamic re-import inside a test
// would return the cached module and the guard could never fail.

// ── View-level pure logic ────────────────────────────────────────────────────

const row = (version: string, pnl = 0): VersionInfo => ({
  version,
  total_pnl: pnl,
  total_trades: 0,
  win_rate: 0,
  sharpe_ratio: 0,
});

describe('sortVersions', () => {
  it('sorts newest first by natural order, so v100 beats v9', () => {
    const sorted = sortVersions([row('v9'), row('v100'), row('v21')]);
    expect(sorted.map((r) => r.version)).toEqual(['v100', 'v21', 'v9']);
  });

  it('handles the real corpus labels, which are not all v<digits>', () => {
    const sorted = sortVersions([
      row('v100'),
      row('v101b'),
      row('v252_replay_2025-03-05'),
      row('v99'),
    ]);
    expect(sorted.map((r) => r.version)).toEqual([
      'v252_replay_2025-03-05',
      'v101b',
      'v100',
      'v99',
    ]);
  });

  it('keeps every row when the corpus repeats a label', () => {
    // Observed live: /versions answers 450 rows with 449 distinct labels —
    // two results files both declare version "v10" internally. Sorting must not
    // dedupe them, or a run silently vanishes from the ledger.
    const sorted = sortVersions([row('v10', 5), row('v11'), row('v10', -3)]);
    expect(sorted).toHaveLength(3);
    expect(sorted.filter((r) => r.version === 'v10')).toHaveLength(2);
  });
});

describe('predecessorOf', () => {
  const sorted = sortVersions([row('v98'), row('v99'), row('v100')]);

  it('returns the next-older run', () => {
    expect(predecessorOf(sorted, 'v100')).toBe('v99');
    expect(predecessorOf(sorted, 'v99')).toBe('v98');
  });

  it('returns null for the oldest run and for an unknown one', () => {
    expect(predecessorOf(sorted, 'v98')).toBeNull();
    expect(predecessorOf(sorted, 'v1')).toBeNull();
  });
});

describe('summariseByRegime', () => {
  it('totals PnL, trades and wins per regime', () => {
    const summary = summariseByRegime([
      { regime: 'normal', pnl: 10 },
      { regime: 'normal', pnl: -4 },
      { regime: 'crisis', pnl: -20 },
      { regime: 'normal', pnl: 6 },
    ]);
    expect(summary).toEqual([
      { regime: 'normal', trades: 3, pnl: 12, wins: 2 },
      { regime: 'crisis', trades: 1, pnl: -20, wins: 0 },
    ]);
  });

  it('buckets an unlabelled trade rather than dropping it, so the totals still sum', () => {
    const summary = summariseByRegime([{ pnl: 5 }, { regime: 'normal', pnl: 1 }]);
    expect(summary.find((s) => s.regime === 'unknown')).toEqual({
      regime: 'unknown',
      trades: 1,
      pnl: 5,
      wins: 1,
    });
    expect(summary.reduce((t, s) => t + s.pnl, 0)).toBe(6);
  });

  it('is empty for no trades', () => {
    expect(summariseByRegime([])).toEqual([]);
  });
});

describe('settleTrades', () => {
  const rejected = (error: Error): PromiseSettledResult<never> => ({
    status: 'rejected',
    reason: error,
  });
  const fulfilled = <T,>(value: T): PromiseSettledResult<T> => ({ status: 'fulfilled', value });

  it('reports the source that failed instead of calling the view empty', () => {
    // The defect: one source 500s, the other legitimately has no rows, and the
    // view drew "No trades — neither source has rows". That reads as an
    // unseeded database and sends the operator looking in the wrong place.
    const boom = new DataSourceError('Omega API: VictoriaService/GetTrades', 500, 'no such table');
    const data = settleTrades(fulfilled([]), rejected(boom));

    expect(data.details).toEqual([]);
    expect(data.rpc).toEqual([]);
    expect(data.failures).toHaveLength(1);
    expect(data.failures[0].source).toBe(TRADE_RPC_SOURCE);
    expect(data.failures[0].error).toBe(boom);
    expect((data.failures[0].error as DataSourceError).bodyExcerpt).toBe('no such table');
  });

  it('keeps the good half and still names the bad one', () => {
    const data = settleTrades(
      rejected(new Error('trade-details is missing')),
      fulfilled([{ sym: 'BTC' }]),
    );
    expect(data.rpc).toEqual([{ sym: 'BTC' }]);
    expect(data.failures.map((f) => f.source)).toEqual([TRADE_DETAILS_SOURCE]);
  });

  it('reports no failure when both sources answer, however empty', () => {
    expect(settleTrades(fulfilled([]), fulfilled([])).failures).toEqual([]);
  });

  it('still fails the panel when both sources fail', () => {
    expect(() =>
      settleTrades(rejected(new Error('details down')), rejected(new Error('rpc down'))),
    ).toThrow('details down');
  });
});

describe('maxDrawdown', () => {
  it('measures peak to trough, not first to last', () => {
    // peak 120, trough 60 → -0.5, even though the series ends higher than it started.
    expect(maxDrawdown([100, 120, 60, 110])).toBeCloseTo(-0.5, 10);
  });

  it('is zero for a monotonically rising curve', () => {
    expect(maxDrawdown([100, 110, 120])).toBe(0);
  });

  it('ignores non-finite points', () => {
    expect(maxDrawdown([100, NaN, 50])).toBeCloseTo(-0.5, 10);
  });
});

describe('formatters', () => {
  it('renders money grouped and signed where sign is the point', () => {
    expect(usd(1240.5)).toBe('$1,240.50');
    expect(usd(-225.89)).toBe('-$225.89');
    expect(signedUsd(36.8)).toBe('+$36.80');
    expect(signedUsd(-225.89)).toBe('-$225.89');
    expect(signedUsd(0)).toBe('$0.00');
  });

  it('renders an absent number as an em dash, never as zero', () => {
    // The omega API omits zero-valued fields, so "absent" arrives as undefined
    // and must not be reported as a real $0.00 / 0.0% / 0.00.
    expect(usd(undefined)).toBe('—');
    expect(signedUsd(null)).toBe('—');
    expect(pct(undefined)).toBe('—');
    expect(ratio(NaN)).toBe('—');
  });

  it('does not clamp percentages, unlike the core progress formatter', () => {
    expect(pct(0.4032)).toBe('40.3%');
    expect(pct(1.85)).toBe('185.0%');
    expect(pct(-0.21)).toBe('-21.0%');
    expect(signedPct(0.1477)).toBe('+14.8%');
  });

  it('colours PnL, leaving flat and absent neutral', () => {
    expect(pnlClass(12)).toBe('text-ok');
    expect(pnlClass(-12)).toBe('text-danger');
    expect(pnlClass(0)).toBe('text-ink3');
    expect(pnlClass(undefined)).toBe('text-ink3');
  });

  it('maps the regime labels the data actually uses', () => {
    // crisis/high_vol/normal — NOT bull/bear/chop.
    expect(regimeColor('crisis')).toBe('#e5675b');
    expect(regimeColor('high_vol')).toBe('#e5c04a');
    expect(regimeColor('normal')).toBe('#4ec97a');
    // 'unknown' is what early cycles emit; it must not be guessed into a colour.
    expect(regimeColor('unknown')).toBe('#6b6b74');
    expect(regimeColor('bull')).toBe('#6b6b74');
  });
});

// ── Phase-2 view logic ───────────────────────────────────────────────────────

describe('failuresForGate', () => {
  // Verbatim from data/v94_gate_result.json.
  const failures = [
    'pnl_floor: v49 -37.86 < v48 130.91',
    'regime_parity[crisis]: v49 -56.29 < v48 +112.98 (delta -169.27)',
    'regime_parity[normal]: v49 -23.71 < v48 -22.79 (delta -0.91)',
  ];

  it('files a failure under its own gate, including the per-regime form', () => {
    expect(failuresForGate(failures, 'pnl_floor')).toEqual([failures[0]]);
    expect(failuresForGate(failures, 'regime_parity')).toEqual([failures[1], failures[2]]);
    expect(failuresForGate(failures, 'drawdown_ceiling')).toEqual([]);
  });

  it('does not let a prefix match a longer gate name', () => {
    expect(failuresForGate(['pnl_floor_extra: nope'], 'pnl_floor')).toEqual([]);
  });

  it('surfaces a failure no gate claims rather than dropping it', () => {
    const orphan = 'something else went wrong';
    expect(unclaimedFailures([...failures, orphan], [...GATE_NAMES])).toEqual([orphan]);
    expect(unclaimedFailures(failures, [...GATE_NAMES])).toEqual([]);
  });
});

describe('summariesIdentical', () => {
  const summary = {
    version: 'v231_crisis_snap_crisis_2024aug_off_crisis_r2',
    pnl: -9507.88,
    trades: 47,
    win_rate: 0.1702,
    max_drawdown: 0,
    regime_pnl: { normal: -5827.6511, high_vol: -2424.5997, crisis: -1255.6327 },
  };

  it('catches the real quirk: different version name, identical numbers', () => {
    // 19 of the 280 gate files in omega's data directory are like this, and the
    // most recently written one is among them. Every delta is zero because the
    // run was gated against itself, which the board has to say out loud.
    expect(summariesIdentical(summary, { ...summary, version: 'v232_crisis_snap_crisis_2024aug_off_crisis_r2' })).toBe(true);
  });

  it('is false when any measurement differs, including one regime', () => {
    expect(summariesIdentical(summary, { ...summary, pnl: -9507.87 })).toBe(false);
    expect(
      summariesIdentical(summary, {
        ...summary,
        regime_pnl: { ...summary.regime_pnl, crisis: -1255.63 },
      }),
    ).toBe(false);
  });

  it('is false when a regime is present on one side only', () => {
    expect(summariesIdentical(summary, { ...summary, regime_pnl: { normal: -5827.6511 } })).toBe(false);
  });

  it('is false when either side is missing — nothing to compare is not sameness', () => {
    expect(summariesIdentical(undefined, summary)).toBe(false);
    expect(summariesIdentical(summary, undefined)).toBe(false);
  });
});

describe('summaryRows', () => {
  const baseline = {
    version: 'v93',
    pnl: 130.91,
    trades: 60,
    win_rate: 0.4833,
    max_drawdown: 0,
    regime_pnl: { normal: -22.7934, high_vol: 40.7237, crisis: 112.9818 },
  };
  const candidate = {
    version: 'v94',
    pnl: -37.86,
    trades: 69,
    win_rate: 0.3043,
    max_drawdown: 0,
    regime_pnl: { normal: -23.7077, high_vol: 42.1353, crisis: -56.2914 },
  };

  it('computes candidate − baseline, in the desk’s regime order', () => {
    const rows = summaryRows(baseline, candidate);
    expect(rows.map((r) => r.label)).toEqual([
      'PnL',
      'Trades',
      'Win rate',
      'Max drawdown',
      'PnL · normal',
      'PnL · high_vol',
      'PnL · crisis',
    ]);
    expect(rows[0].delta).toBeCloseTo(-168.77, 10);
    expect(rows[1].delta).toBe(9);
    expect(rows[6].delta).toBeCloseTo(-169.2732, 10);
  });

  it('marks drawdown as lower-is-better, so a smaller number is not painted red', () => {
    expect(summaryRows(baseline, candidate).find((r) => r.label === 'Max drawdown')?.lowerIsBetter).toBe(true);
  });

  it('leaves a delta null when one side is missing, rather than calling it zero', () => {
    const rows = summaryRows(baseline, undefined);
    expect(rows[0].baseline).toBe(130.91);
    expect(rows[0].candidate).toBeUndefined();
    expect(rows[0].delta).toBeNull();
  });

  it('carries a regime only one side saw, and an unknown regime after the known ones', () => {
    const rows = summaryRows(
      { regime_pnl: { normal: 1, chop: 5 } },
      { regime_pnl: { normal: 2 } },
    );
    expect(rows.map((r) => r.label).slice(4)).toEqual(['PnL · normal', 'PnL · chop']);
    expect(rows[5].candidate).toBeUndefined();
    expect(rows[5].delta).toBeNull();
  });
});

describe('the conviction funnel', () => {
  // A reduction of data/decision_traces/bt_v132a_crisis.jsonl: in the real file
  // 770 ticker-cycles produce 170 proposals and 146 trades, and `blacklist`
  // blocks 560 rows before a proposal ever exists.
  const traces = [
    { ticker: 'BTCUSDT', cycle: 1, proposal: 'NONE', blocking_filter: 'blacklist', final_decision: 'HOLD' },
    { ticker: 'ETHUSDT', cycle: 1, proposal: 'LONG', blocking_filter: '', final_decision: 'TRADE' },
    { ticker: 'ADAUSDT', cycle: 1, proposal: 'SHORT', blocking_filter: 'position_limit', final_decision: 'FILTERED' },
    { ticker: 'BTCUSDT', cycle: 2, proposal: 'NONE', blocking_filter: 'blacklist', final_decision: 'HOLD' },
    { ticker: 'ETHUSDT', cycle: 2, proposal: 'LONG', blocking_filter: '', final_decision: 'TRADE' },
  ];

  it('counts the two drop-offs separately, because they point at different code', () => {
    // A HOLD is the strategy declining to propose; a FILTERED is a proposal the
    // pipeline killed. Collapsing them into "didn't trade" loses the finding.
    expect(funnelCounts(traces)).toEqual({
      evaluated: 5,
      proposed: 3,
      traded: 2,
      held: 2,
      filtered: 1,
      long: 2,
      short: 1,
    });
  });

  it('treats an absent proposal as no proposal, not as an unknown side', () => {
    expect(funnelCounts([{ cycle: 1 }]).proposed).toBe(0);
    expect(isProposal({ proposal: 'none' })).toBe(false);
    expect(isProposal({ proposal: 'LONG' })).toBe(true);
  });

  it('is a zero funnel for no traces, not a division by zero', () => {
    expect(funnelCounts([])).toEqual({ evaluated: 0, proposed: 0, traded: 0, held: 0, filtered: 0, long: 0, short: 0 });
  });

  it('counts every blocking filter, including the ones that fire before a proposal', () => {
    // `blacklist` blocks a ticker before a proposal exists — 560 of 770 rows in
    // the real file. Counting only killed proposals would make the single
    // biggest reason a run sat out invisible.
    expect(blockingBreakdown(traces)).toEqual([
      { filter: 'blacklist', count: 2, blockedProposals: 0 },
      { filter: 'position_limit', count: 1, blockedProposals: 1 },
    ]);
  });

  it('tallies the writer’s own decisions, so a disagreement with the funnel is visible', () => {
    expect(decisionCounts(traces)).toEqual([
      { decision: 'HOLD', count: 2 },
      { decision: 'TRADE', count: 2 },
      { decision: 'FILTERED', count: 1 },
    ]);
  });

  it('lists the cycles present, ascending and deduplicated', () => {
    expect(cyclesOf(traces)).toEqual([1, 2]);
    expect(cyclesOf([{ ticker: 'X' }])).toEqual([]);
  });
});

describe('the forensics report readers', () => {
  // Trimmed from data/v93-v94-forensics.json. The keys really are v35/v48.
  const report = {
    baselines: {
      v35: { version: 'v93', pnl: 130.91 },
      v48: { version: 'v94', pnl: -37.86 },
    },
    conviction_histogram: {
      v35: { hold_threshold: 0.2, trade_band_count: 1, hold_band_count: 59, trade_band_pct: 0.0167 },
      v48: { hold_threshold: 0.2, trade_band_count: 1, hold_band_count: 68, trade_band_pct: 0.0145 },
    },
    signal_contribution_delta_proxy: {
      per_symbol: { ADAUSDT: -55.1537, ARBUSDT: -60.935, ETHUSDT: -6.6902, NEARUSDT: -45.997 },
    },
    regime_breakdown: {
      crisis: { v35_pnl: 112.9818, v48_pnl: -56.2914, delta: -169.2732 },
    },
  };

  it('takes the two sides from insertion order, not from the filename pair', () => {
    // The quirk this exists for: v93-v94-forensics.json keys its sides "v35"
    // and "v48" — run_diff.py's hard-coded labels. Indexing by the pair in the
    // filename would find nothing at all.
    expect(reportKeys(report)).toEqual(['v35', 'v48']);
    expect(sideLabel(report, 'v35')).toBe('v93');
    expect(sideLabel(report, 'v48')).toBe('v94');
  });

  it('falls back to the histogram keys, and gives up honestly', () => {
    expect(reportKeys({ conviction_histogram: { a: {}, b: {} } })).toEqual(['a', 'b']);
    expect(reportKeys({})).toBeNull();
    expect(reportKeys({ baselines: { only: {} } })).toBeNull();
    // With no keys, the label is the key itself rather than an invented name.
    expect(sideLabel({}, 'v35')).toBe('v35');
  });

  it('sorts symbols by the size of the move, not by its sign', () => {
    expect(symbolDeltas(report).map((s) => s.symbol)).toEqual([
      'ARBUSDT',
      'ADAUSDT',
      'NEARUSDT',
      'ETHUSDT',
    ]);
    expect(symbolDeltas({}).length).toBe(0);
  });

  it('derives the per-regime field names from the report’s own keys', () => {
    // `v35_pnl` / `v48_pnl` are built from the keys; hard-coding them would work
    // on every report in the repo today and break on the next one.
    expect(regimeRows(report, ['v35', 'v48'])).toEqual([
      { regime: 'crisis', baseline: 112.9818, candidate: -56.2914, delta: -169.2732 },
    ]);
    // Without keys the delta still survives — it is not key-derived.
    expect(regimeRows(report, null)).toEqual([
      { regime: 'crisis', baseline: undefined, candidate: undefined, delta: -169.2732 },
    ]);
  });

  it('pairs the histogram bands and measures for the two sides', () => {
    expect(histogramGroups(report, ['v35', 'v48'])).toEqual([
      { label: 'trade band', values: [1, 1] },
      { label: 'hold band', values: [59, 68] },
    ]);
    expect(histogramGroups(report, null)).toEqual([]);
    expect(histogramRows(report, ['v35', 'v48'])[0]).toEqual({
      label: 'hold threshold',
      kind: 'ratio',
      baseline: 0.2,
      candidate: 0.2,
    });
    expect(histogramRows({}, ['v35', 'v48'])).toEqual([]);
  });
});

describe('the journal index', () => {
  it('sorts newest first, naturally — V270 above V99', () => {
    expect(
      sortJournal([
        { version: 'V99', hasPreRegistration: true },
        { version: 'V270', hasPreRegistration: true },
        { version: 'V262', hasPreRegistration: true },
      ]).map((e) => e.version),
    ).toEqual(['V270', 'V262', 'V99']);
  });

  it('names a cell that has a verdict but was never pre-registered', () => {
    // The failure mode the whole practice exists to prevent: a result with no
    // promise to measure it against. It gets the danger colour, not a shrug.
    expect(entryStatus({ version: 'V262', hasPreRegistration: false, verdictFiles: ['V262_AUDIT_VERDICT.md'] })).toEqual({
      label: 'verdict only — not pre-registered',
      color: '#e5675b',
      verdicts: 1,
    });
  });

  it('distinguishes a closed cell from one still in flight', () => {
    expect(entryStatus({ version: 'V261', hasPreRegistration: true, verdictFiles: ['V261_VERDICT.md'] }).label).toBe('closed');
    expect(entryStatus({ version: 'V270', hasPreRegistration: true }).label).toBe('open — no verdict');
    expect(entryStatus({ version: 'V270', hasPreRegistration: true }).verdicts).toBe(0);
  });
});

describe('the shell-local focus store', () => {
  afterEach(() => { resetFocusVersion(); });

  it('carries a version between views, which onOpenView cannot', () => {
    // `onOpenView(viewId)` has no second argument, so "open Gates for V270" has
    // no channel in the guest contract. This is the plugin-internal substitute.
    const seen: (string | null)[] = [];
    const unsubscribe = subscribeFocusVersion(() => { seen.push(getFocusVersion()); });

    setFocusVersion('V270');
    expect(getFocusVersion()).toBe('V270');
    setFocusVersion(null);
    expect(seen).toEqual(['V270', null]);

    unsubscribe();
    setFocusVersion('v94');
    expect(seen).toEqual(['V270', null]); // no longer listening
  });

  it('does not notify on a write of the same value, so a re-announcing view cannot loop', () => {
    let notifications = 0;
    subscribeFocusVersion(() => { notifications++; });
    setFocusVersion('v94');
    setFocusVersion('v94');
    expect(notifications).toBe(1);
  });
});
