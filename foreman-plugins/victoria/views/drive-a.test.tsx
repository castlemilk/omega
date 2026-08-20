/**
 * Three places this shell claimed something it could not substantiate.
 *
 * Same technique as `../views.test.tsx`: `renderToStaticMarkup` and assertions
 * on the *text an operator reads*, plus direct assertions on the exported pure
 * functions the copy is derived from. Where a fix is a rule rather than a
 * string — "an absent snapshot has no direction", "a stale record is not a live
 * one" — the rule is asserted as a value so a later refactor of the markup
 * cannot quietly reinstate the claim.
 *
 * The fixtures are the payloads observed live on 2026-08-20:
 *   - `GetSignals` on the unseeded database: `{"compositeDirection":"SHORT"}`;
 *   - `/api/v1/training/metrics`: status "complete", cycle 45, total 0;
 *   - `/api/v1/training/progress`: the checkpoint-array projection, which
 *     carries no run id and a "unknown" regime at confidence 0.
 */
import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { DataSourceError } from '@omega-harness/usecase-kit';
import type {
  SignalCorrelation,
  SignalsSnapshot,
  TrainingMetrics,
  TrainingProgress,
} from '../client.js';
import { SignalsPanel, snapshotIsAbsent, snapshotTiles } from './Signals.js';
import { LiveMetrics, ProgressDetail, liveness, plottable, unplottableReason } from './Live.js';
import { GATES_VIEW_ID, gateLabel, openGatesFor } from './Journal.js';
import { GateLoadFailure } from './Gates.js';
import { getFocusVersion, resetFocusVersion } from '../store.js';

// ── V1 · the direction an empty snapshot claimed ─────────────────────────────

/** What GetSignals answers against a database no run has written to. */
const EMPTY_SNAPSHOT: SignalsSnapshot = { compositeDirection: 'SHORT' };

const NO_CORRELATION: SignalCorrelation = { signals: [], matrix: [], n_observations: 0 };

describe('the Signals snapshot tiles', () => {
  it('reads every headline tile as an em dash when the snapshot is empty', () => {
    expect(snapshotTiles(EMPTY_SNAPSHOT)).toEqual({
      composite: '—',
      direction: '—',
      oosSharpe: '—',
      signals: '—',
    });
  });

  it('does not put a SHORT on the board for a composite that was never computed', () => {
    const html = renderToStaticMarkup(
      <SignalsPanel snapshot={EMPTY_SNAPSHOT} correlation={NO_CORRELATION} />,
    );
    expect(html).not.toContain('SHORT');
    expect(html).not.toContain('LONG');
    expect(html).toContain('GetSignals answered with an empty snapshot');
    expect(html).toContain('a direction is the sign of a composite');
    expect(html).toContain('no snapshot to count');
  });

  it('treats compositeDirection as no evidence of a snapshot, and a number as evidence', () => {
    // The string survives proto3's omit-zero rule whatever it holds, so it can
    // never be the thing that proves a snapshot exists.
    expect(snapshotIsAbsent({ compositeDirection: 'SHORT' })).toBe(true);
    expect(snapshotIsAbsent({})).toBe(true);
    expect(snapshotIsAbsent({ compositeScore: 0.31 })).toBe(false);
    expect(snapshotIsAbsent({ oosSharpe: 1.17 })).toBe(false);
    expect(snapshotIsAbsent({ signals: [{ name: 'momentum' }] })).toBe(false);
  });

  it('renders a genuine composite of exactly 0 as a number, not as an em dash', () => {
    // Connect's proto3 JSON drops a zero-valued field, so a real 0.0 composite
    // arrives byte-identical to a missing one. Once the message is known to be
    // populated — here, by its signals — the missing number IS the zero.
    const elided: SignalsSnapshot = {
      signals: [{ name: 'momentum', currentValue: 0.4 }],
      compositeDirection: 'LONG',
    };
    expect(snapshotTiles(elided)).toEqual({
      composite: '0.0000',
      direction: 'LONG',
      oosSharpe: '0.00',
      signals: '1',
    });

    const explicit: SignalsSnapshot = {
      signals: [{ name: 'momentum' }],
      compositeScore: 0,
      compositeDirection: 'SHORT',
      oosSharpe: 1.171,
    };
    expect(snapshotTiles(explicit)).toEqual({
      composite: '0.0000',
      direction: 'SHORT',
      oosSharpe: '1.17',
      signals: '1',
    });

    const html = renderToStaticMarkup(
      <SignalsPanel snapshot={explicit} correlation={NO_CORRELATION} />,
    );
    expect(html).toContain('0.0000');
    expect(html).toContain('SHORT');
    expect(html).not.toContain('GetSignals answered with an empty snapshot');
  });
});

// ── V2 · the Journal → Gates jump ────────────────────────────────────────────

describe('the Journal jump to the gate board', () => {
  it('carries the journal label in the spelling every gate file on disk uses', () => {
    expect(gateLabel('V270')).toBe('v270');
    expect(gateLabel('V232_CRISIS_SNAP_R2')).toBe('v232_crisis_snap_r2');
    // Already-lowercase labels are untouched, so a label typed into the picker
    // round-trips.
    expect(gateLabel('v94')).toBe('v94');
  });

  it('explains a 404 as two label families, not as a run that died', () => {
    // Lowercasing gets the spelling right; it does not conjure a file. `v270`
    // still 404s, and the honest reason is that no per-cell gate was ever run
    // for that journal cell — NOT that the run failed to finish, which is what
    // this paragraph used to assert about every recent label.
    const error = new DataSourceError(
      'Omega API: GET /api/v1/training/gates?version=v270 failed',
      404,
      'no gate result for version "v270"',
    );
    const html = renderToStaticMarkup(<GateLoadFailure error={error} version="v270" />);
    expect(html).toContain('A missing gate result is not a failed gate');
    expect(html).toContain('cell labels are a different family from the journal');
    expect(html).toContain('a per-cell gate was never run for it');
    expect(html).toContain('says nothing about whether that run finished');
    expect(html).toContain('the two sets do not currently intersect');
    // The sentence that was false for every scoring-pass journal cell.
    expect(html).not.toContain('the run itself never reached the end');
    expect(html).not.toContain('Since that repoint a file is written for');
  });

  it('seeds the Gates picker with v270, not V270, and then opens Gates', () => {
    resetFocusVersion();
    const opened: string[] = [];
    openGatesFor('V270', (viewId) => opened.push(viewId));
    expect(getFocusVersion()).toBe('v270');
    expect(opened).toEqual([GATES_VIEW_ID]);
    expect(GATES_VIEW_ID).toBe('victoria-gates');
    resetFocusVersion();
  });
});

// ── V4 · a stale record presented as a live run ──────────────────────────────

/** `/api/v1/training/metrics`, 2026-08-20: a record of a run that is over. */
const STALE_METRICS: TrainingMetrics = {
  total_trades: 312,
  win_rate: 0.4327,
  total_pnl: 598.77,
  realised_pnl: 598.77,
  unrealised_pnl: 0,
  memory_count: { episodic: 41, semantic: 12, total: 53 },
  symbol_breakdown: [],
  recent_trades: [],
  signal_health: [],
  current_cycle: 45,
  total_cycles: 0,
  status: 'complete',
};

const ACTIVE_METRICS: TrainingMetrics = {
  ...STALE_METRICS,
  current_cycle: 12,
  total_cycles: 200,
  status: 'running',
};

const NOW = Date.parse('2026-08-20T00:00:00Z');

/** The checkpoint-array projection: no run id, "unknown" regime, flat zeros. */
const STALE_PROGRESS: TrainingProgress = {
  run_id: '',
  current_cycle: 45,
  total_cycles: 0,
  started_at: '2026-08-17T00:00:00Z',
  status: 'complete',
  pnl_history: [1, 2, 3, 4, 5, 6].map((cycle) => ({ cycle, pnl: 0 })),
  win_rate_history: [1, 2, 3, 4, 5, 6].map((cycle) => ({ cycle, win_rate: 0 })),
  activity_log: [],
  current_regime: { name: 'unknown', confidence: 0 },
};

const ACTIVE_PROGRESS: TrainingProgress = {
  run_id: 'v271-wf',
  current_cycle: 12,
  total_cycles: 200,
  started_at: '2026-08-19T23:30:00Z',
  status: 'running',
  pnl_history: [
    { cycle: 10, pnl: -12.5 },
    { cycle: 11, pnl: 4.25 },
    { cycle: 12, pnl: 36.8 },
  ],
  win_rate_history: [
    { cycle: 10, win_rate: 0.4 },
    { cycle: 11, win_rate: 0.45 },
    { cycle: 12, win_rate: 0.5 },
  ],
  activity_log: [{ cycle: 12, type: 'trade', message: 'opened BTCUSDT long' }],
  current_regime: { name: 'crisis', confidence: 0.82 },
};

describe('liveness', () => {
  it('names both reasons the observed payload is not a run in progress', () => {
    const state = liveness(STALE_METRICS);
    expect(state.live).toBe(false);
    expect(state.reasons).toHaveLength(2);
    expect(state.reasons[0]).toContain('status “complete”');
    expect(state.reasons[0]).toContain('has not been written in the last ten minutes');
    expect(state.reasons[1]).toContain('total_cycles is 0');
    expect(state.reasons[1]).toContain('“45 / 0” is not a progress reading');
  });

  it('calls a coherent running payload live, and nothing else', () => {
    expect(liveness(ACTIVE_METRICS)).toEqual({ live: true, reasons: [] });
    expect(liveness({ status: 'running', current_cycle: 201, total_cycles: 200 })).toEqual({
      live: false,
      reasons: ['the cycle counter (201) is past the recorded total (200)'],
    });
    expect(liveness({ status: 'running', current_cycle: 3, total_cycles: 200 }).live).toBe(true);
    expect(liveness({}).reasons[0]).toBe('the API reported no status at all');
  });
});

describe('the Live aggregate strip', () => {
  it('shows an em dash instead of “45 / 0”, and says why', () => {
    const html = renderToStaticMarkup(<LiveMetrics metrics={STALE_METRICS} />);
    // Not as a tile value. It still appears inside the reason that explains why
    // it is not a reading — quoted, which is the opposite of claiming it.
    expect(html).not.toContain('>45 / 0<');
    expect(html).toContain('“45 / 0” is not a progress reading');
    expect(html).toContain('no run in progress');
    expect(html).toContain('No training run in progress');
    expect(html).toContain('status “complete”');
    expect(html).toContain('total_cycles is 0');
    // The aggregates beside it ARE real and stay on screen, labelled as what
    // they are rather than blanked.
    expect(html).toContain('+$598.77');
    expect(html).toContain('43.3%');
    expect(html).toContain('312');
  });

  it('renders a running payload with its real cycle numbers and no idle copy', () => {
    const html = renderToStaticMarkup(<LiveMetrics metrics={ACTIVE_METRICS} />);
    expect(html).toContain('12 / 200');
    expect(html).toContain('running');
    expect(html).not.toContain('No training run in progress');
    expect(html).not.toContain('no run in progress');
  });
});

describe('the Live run-detail panel', () => {
  it('reports the stale record as a record, with its cycle, missing run id and age', () => {
    const html = renderToStaticMarkup(<ProgressDetail progress={STALE_PROGRESS} now={NOW} />);
    expect(html).toContain('No training run in progress');
    expect(html).toContain('Last recorded progress: cycle <span class="font-mono">45</span>');
    expect(html).toContain('the record carries no cycle total');
    expect(html).toContain('no run id');
    expect(html).toContain('which has no <span class="font-mono">run_id</span> field');
    expect(html).toContain('first checkpoint 3d ago');
    expect(html).toContain('What is below is that record, not a run in flight');
  });

  it('plots nothing for a column of zeros, and says it is a column of zeros', () => {
    const html = renderToStaticMarkup(<ProgressDetail progress={STALE_PROGRESS} now={NOW} />);
    expect(html).not.toContain('<svg');
    expect(html).not.toContain('<path');
    expect(html).toContain('nothing to plot — all 6 recorded points are the same value ($0.00)');
    expect(html).toContain('nothing to plot — all 6 recorded points are the same value (0.0%)');
  });

  it('does not dress an unclassified regime as a measurement', () => {
    const html = renderToStaticMarkup(<ProgressDetail progress={STALE_PROGRESS} now={NOW} />);
    expect(html).not.toContain('unknown');
    expect(html).not.toContain('0%<');
    expect(html).toContain('regime not classified');
  });

  it('renders a live run unchanged: sparklines, regime, activity', () => {
    const html = renderToStaticMarkup(<ProgressDetail progress={ACTIVE_PROGRESS} now={NOW} />);
    expect(html).toContain('<svg');
    expect(html).toContain('crisis');
    expect(html).toContain('82%');
    expect(html).toContain('opened BTCUSDT long');
    expect(html).not.toContain('No training run in progress');
    expect(html).not.toContain('nothing to plot');
  });

  it('distinguishes an empty series from a flat one from a single point', () => {
    expect(plottable([])).toBe(false);
    expect(plottable([1])).toBe(false);
    expect(plottable([0, 0, 0])).toBe(false);
    expect(plottable([0, 0, 1])).toBe(true);
    expect(unplottableReason([], (v) => String(v))).toBe(
      'nothing to plot — the record carries no points for this series',
    );
    expect(unplottableReason([7], (v) => String(v))).toBe(
      'nothing to plot — one recorded point is not a trend',
    );
    expect(unplottableReason([7, 7], (v) => String(v))).toBe(
      'nothing to plot — all 2 recorded points are the same value (7)',
    );
  });
});
