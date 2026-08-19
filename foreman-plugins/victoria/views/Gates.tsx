/**
 * Gates — the ship/no-ship board.
 *
 * `data/{version}_gate_result.json`, and only that file, decides whether a run
 * is allowed to become the new baseline. This view is that decision, rendered.
 *
 * TWO shapes reach it and both are rendered honestly:
 *
 *   - **Standing** (`omega/eval/standing_gates.py`, from 2026-08-18) — carries a
 *     `verdict` of PASS / FAIL / NO_OP / NO_BASELINE / ERROR, per-gate
 *     `pass|fail|not_evaluated`, and the floor it was judged against. There is
 *     no baseline RUN in this shape. The bar is the family's PER-CELL floor
 *     ($0: did this cell lose money); the journal's campaign mean is rendered
 *     as an amber ADVISORY on a passing tile, never as a failure tint, because
 *     it is a mean over a skewed window distribution and not a per-cell bar.
 *     The N-1 sibling is likewise an informational no-op detector.
 *   - **Legacy** (`omega/eval/v49_gates.py`) — the six-gate sibling comparison,
 *     280 archived files of it. A file with no `verdict` renders exactly as it
 *     did before the standing board existed. That is a hard requirement: the
 *     archive is evidence, and re-interpreting it in a new vocabulary would be
 *     rewriting history.
 *
 * Three things it must not do, all learned from the real corpus of 280 gate
 * files in the omega data directory:
 *
 *   1. **Never infer a gate's result from the failure list.** `gates` is the
 *      verdict; `failures` is the prose. A gate the file does not mention is
 *      reported as "not reported", not as a pass — older files predate later
 *      gates, and drawing a green tile for a gate that never ran is the single
 *      most dangerous thing this view could do.
 *   2. **Never hide identical summaries.** In 19 of the 280 files — *including
 *      the newest one*, `v232_crisis_snap_crisis_2024aug_off_crisis_r2` — the
 *      baseline and candidate summaries carry byte-identical numbers under two
 *      different version names. A board that silently rendered `+$0.00` deltas
 *      would read as "a run that changed nothing" when what actually happened is
 *      that the gate ran against itself. It is called out in words.
 *   3. **Never present a 404 as a failed gate.** No gate file means the gates
 *      never ran. The view says so and names the producer.
 */
import { Pill } from '@omega-harness/usecase-kit/ui';
import type { UseCaseViewProps } from '@omega-harness/usecase-kit';
import {
  GATE_NAMES,
  STANDING_GATE_NAMES,
  type GateDetail,
  type GateResult,
  type GateSummary,
  type GridFamilyRuling,
  type GridRulerResult,
} from '../client.js';
import { pct, pnlClass, signedUsd, usd } from '../format.js';
import { useVictoriaGates, useVictoriaGridRuler } from '../hooks.js';
import { setFocusVersion, useFocusVersion } from '../store.js';
import { Card, EmptyNote, ErrorNote, LoadingNote, Num, Table, Txt, ViewFrame } from './chrome.js';
import { VersionPicker } from './VersionPicker.js';

/** Human labels for the six gates. The keys are the file's, verbatim. */
const GATE_LABELS: Record<string, string> = {
  pnl_floor: 'PnL floor',
  regime_parity: 'Regime parity',
  drawdown_ceiling: 'Drawdown ceiling',
  trade_count_floor: 'Trade-count floor',
  signal_integrity: 'Signal integrity',
  auto_apply_audit: 'Auto-apply audit',
};

/** What each gate asserts, so a red tile is legible without reading the Python. */
const GATE_BLURBS: Record<string, string> = {
  pnl_floor: 'candidate PnL ≥ baseline PnL',
  regime_parity: 'no regime went backwards',
  drawdown_ceiling: 'drawdown stayed under the ceiling',
  trade_count_floor: 'at least 20 trades',
  signal_integrity: 'signal tests still pass',
  auto_apply_audit: 'meta-analyst changes were safe',
};

/**
 * The failure lines belonging to one gate.
 *
 * The producer writes them as `"<gate>: …"` or `"<gate>[<regime>]: …"` — e.g.
 * `regime_parity[crisis]: v49 -56.29 < v48 +112.98`. Matched on that prefix so a
 * gate's own evidence lands under its own tile; anything unmatched is still
 * rendered, in an "other failures" list, because a failure string nobody claims
 * is exactly the kind of thing that must not disappear.
 */
export function failuresForGate(failures: readonly string[], gate: string): string[] {
  return failures.filter((f) => f.startsWith(`${gate}:`) || f.startsWith(`${gate}[`));
}

/** Failure strings that matched no known gate prefix. */
export function unclaimedFailures(failures: readonly string[], gates: readonly string[]): string[] {
  return failures.filter((f) => !gates.some((g) => f.startsWith(`${g}:`) || f.startsWith(`${g}[`)));
}

/**
 * Whether the two summaries carry the same measurements.
 *
 * Version is excluded on purpose: it is the field that differs in the 19 files
 * where everything else is identical, and it is that combination — different
 * name, same numbers — that this predicate exists to catch.
 */
export function summariesIdentical(a?: GateSummary, b?: GateSummary): boolean {
  if (!a || !b) return false;
  if (a.pnl !== b.pnl || a.trades !== b.trades) return false;
  if (a.win_rate !== b.win_rate || a.max_drawdown !== b.max_drawdown) return false;
  const ra = a.regime_pnl ?? {};
  const rb = b.regime_pnl ?? {};
  const keys = new Set([...Object.keys(ra), ...Object.keys(rb)]);
  for (const k of keys) if (ra[k] !== rb[k]) return false;
  return true;
}

export interface SummaryRow {
  label: string;
  kind: 'usd' | 'pct' | 'count';
  baseline?: number;
  candidate?: number;
  /** null when either side is missing — a delta against nothing is not zero. */
  delta: number | null;
  /** True when a *lower* number is the better one (drawdown). */
  lowerIsBetter?: boolean;
}

/** The regime order the desk reads in; anything else follows, alphabetically. */
const REGIME_ORDER = ['normal', 'high_vol', 'crisis'];

function delta(a?: number, b?: number): number | null {
  return typeof a === 'number' && typeof b === 'number' ? b - a : null;
}

/** The comparison table, as rows — pure, so the arithmetic is assertable. */
export function summaryRows(baseline?: GateSummary, candidate?: GateSummary): SummaryRow[] {
  const rows: SummaryRow[] = [
    { label: 'PnL', kind: 'usd', baseline: baseline?.pnl, candidate: candidate?.pnl, delta: delta(baseline?.pnl, candidate?.pnl) },
    { label: 'Trades', kind: 'count', baseline: baseline?.trades, candidate: candidate?.trades, delta: delta(baseline?.trades, candidate?.trades) },
    { label: 'Win rate', kind: 'pct', baseline: baseline?.win_rate, candidate: candidate?.win_rate, delta: delta(baseline?.win_rate, candidate?.win_rate) },
    {
      label: 'Max drawdown',
      kind: 'pct',
      baseline: baseline?.max_drawdown,
      candidate: candidate?.max_drawdown,
      delta: delta(baseline?.max_drawdown, candidate?.max_drawdown),
      lowerIsBetter: true,
    },
  ];

  const ra = baseline?.regime_pnl ?? {};
  const rb = candidate?.regime_pnl ?? {};
  const known = REGIME_ORDER.filter((r) => r in ra || r in rb);
  const extra = [...new Set([...Object.keys(ra), ...Object.keys(rb)])]
    .filter((r) => !REGIME_ORDER.includes(r))
    .sort();
  for (const regime of [...known, ...extra]) {
    rows.push({
      label: `PnL · ${regime}`,
      kind: 'usd',
      baseline: ra[regime],
      candidate: rb[regime],
      delta: delta(ra[regime], rb[regime]),
    });
  }
  return rows;
}

function formatValue(kind: SummaryRow['kind'], value?: number): string {
  if (value === undefined) return '—';
  if (kind === 'usd') return usd(value);
  if (kind === 'pct') return pct(value);
  return String(value);
}

function formatDelta(row: SummaryRow): string {
  if (row.delta === null) return '—';
  if (row.kind === 'usd') return signedUsd(row.delta);
  if (row.kind === 'pct') return `${row.delta > 0 ? '+' : ''}${pct(row.delta)}`;
  return `${row.delta > 0 ? '+' : ''}${String(row.delta)}`;
}

function deltaTone(row: SummaryRow): string {
  if (row.delta === null || row.delta === 0) return 'text-ink3';
  const good = row.lowerIsBetter === true ? row.delta < 0 : row.delta > 0;
  return good ? 'text-ok' : 'text-danger';
}

function GateTile({
  gate,
  result,
  failures,
}: {
  gate: string;
  result: boolean | undefined;
  failures: readonly string[];
}) {
  const known = result !== undefined;
  const tone = !known
    ? 'border-line bg-card'
    : result
      ? 'border-ok/30 bg-ok/10'
      : 'border-danger/30 bg-danger/10';
  const mark = !known ? '—' : result ? 'PASS' : 'FAIL';
  const markTone = !known ? 'text-faint' : result ? 'text-ok' : 'text-danger';

  return (
    <div className={`flex flex-col gap-1.5 rounded-md border px-3.5 py-3 ${tone}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium text-ink">{GATE_LABELS[gate] ?? gate}</span>
        <span className={`font-mono text-[10px] font-semibold tracking-[.08em] ${markTone}`}>{mark}</span>
      </div>
      <div className="font-mono text-[9.5px] text-faint">
        {known ? (GATE_BLURBS[gate] ?? gate) : 'not reported by this gate file'}
      </div>
      {failures.map((f) => (
        <div key={f} className="break-words font-mono text-[10px] leading-relaxed text-danger-tint">
          {f}
        </div>
      ))}
    </div>
  );
}

// ── Standing-baseline shape (omega/eval/standing_gates.py, 2026-08-18) ───────
//
// A file carries a `verdict` or it does not. When it does not, everything below
// is inert and the legacy six-tile board renders byte-for-byte as before — the
// 280 archived gate files must keep reading exactly as they read yesterday.

/** Human labels for the standing gates. Keys are the file's, verbatim. */
const STANDING_GATE_LABELS: Record<string, string> = {
  cell_pnl_floor: 'Per-cell PnL floor',
  trade_count_floor: 'Trade-count floor',
  drawdown_ceiling: 'Drawdown ceiling',
};

const STANDING_GATE_BLURBS: Record<string, string> = {
  cell_pnl_floor: 'candidate PnL ≥ the per-cell floor ($0 — did this cell lose money)',
  trade_count_floor: 'at least 20 closed trades',
  drawdown_ceiling: 'only evaluated when the run emitted a drawdown number',
};

/**
 * The colour and the *sentence* for each verdict.
 *
 * The sentence matters more than the colour. `NO_OP` and `NO_BASELINE` are the
 * two states an operator has never seen before, and both of them used to be
 * rendered as something false — a green board, or no board at all — so each one
 * says in plain words what actually happened.
 */
export const VERDICT_TONE: Record<
  string,
  { color: string; label: string; sentence: string }
> = {
  PASS: {
    color: '#4ec97a',
    label: 'gates passed',
    sentence:
      'Every evaluated gate passed. The per-cell bar is the $0 floor — did this cell lose money — not the campaign mean; a cell under its family’s campaign mean still passes, with an amber advisory on the tile.',
  },
  FAIL: {
    color: '#e5675b',
    label: 'gates failed',
    sentence: 'At least one gate failed. The failing gate’s own numbers are under its tile.',
  },
  NO_OP: {
    color: '#e0a33a',
    label: 'no-op',
    sentence:
      'This run used a frozen cache and reproduced a prior run exactly — same trades, same PnL, new label. It measured nothing new, so a green board here would be vacuous. 18 of the archived gate files are this shape and every one of them reads as an all-green pass.',
  },
  NO_BASELINE: {
    color: '#a78bfa',
    label: 'no baseline',
    sentence:
      'This cell’s regime family could not be resolved, so no per-cell floor could be applied and the PnL gate was not evaluated. This is NOT a pass. Under the old gates this case wrote no file at all — a silent skip. Fix it by adding a family_patterns entry to data/standing_baseline.json or by naming the cell after its regime.',
  },
  ERROR: {
    color: '#e5675b',
    label: 'gate error',
    sentence:
      'Gate evaluation itself raised. The training run survived; this file is the record of the failure, which the old code swallowed.',
  },
};

const STATUS_TONE: Record<string, { border: string; bg: string; text: string; mark: string }> = {
  pass: { border: '#4ec97a4d', bg: '#4ec97a1a', text: '#4ec97a', mark: 'PASS' },
  fail: { border: '#e5675b4d', bg: '#e5675b1a', text: '#e5675b', mark: 'FAIL' },
  not_evaluated: {
    border: 'transparent',
    bg: 'transparent',
    text: '#7c8590',
    mark: 'NOT EVALUATED',
  },
};

/**
 * The amber advisory line for a passing gate that sits under its family's
 * campaign mean, or `null` when there is nothing to say.
 *
 * This is deliberately NOT a failure and must never be tinted as one. The
 * campaign means (+$599 / +$2,997 / +$30) are means of skewed per-regime
 * walk-forward distributions — crisis's own median window is +$65 — so a cell
 * under one is an ordinary cell, not a broken one. The ruler that can actually
 * be read against the mean is grid-level, which is why the note says so.
 */
export function campaignMeanAdvisory(detail: GateDetail): string | null {
  if (detail.advisory !== 'below_campaign_mean') return null;
  const margin = detail.campaign_mean_margin_usd;
  const shortfall = typeof margin === 'number' ? usd(Math.abs(margin)) : '—';
  const mean = typeof detail.campaign_mean_usd === 'number' ? signedUsd(detail.campaign_mean_usd) : '—';
  return `below campaign mean by ${shortfall} (mean ${mean}) — informational; the campaign ruler is grid-level, not per-cell.`;
}

/** The evidence line under a standing gate tile, as text. Pure, so it is assertable. */
export function standingGateEvidence(gate: string, detail: GateDetail): string[] {
  const lines: string[] = [];
  if (gate === 'cell_pnl_floor' && typeof detail.floor_usd === 'number') {
    lines.push(
      `${signedUsd(detail.candidate_pnl_usd ?? 0)} vs floor ${signedUsd(detail.floor_usd)}` +
        (typeof detail.margin_usd === 'number' ? ` (margin ${signedUsd(detail.margin_usd)})` : ''),
    );
    if (typeof detail.family === 'string') lines.push(`family: ${detail.family}`);
  }
  if (gate === 'trade_count_floor' && typeof detail.trades === 'number') {
    lines.push(`${String(detail.trades)} trades vs floor ${String(detail.floor ?? 20)}`);
  }
  if (gate === 'drawdown_ceiling' && typeof detail.candidate_max_drawdown_usd === 'number') {
    lines.push(
      `${usd(detail.candidate_max_drawdown_usd)}` +
        (typeof detail.ceiling_usd === 'number' ? ` vs ceiling ${usd(detail.ceiling_usd)}` : ''),
    );
  }
  if (typeof detail.reason === 'string' && detail.reason !== '') lines.push(detail.reason);
  return lines;
}

function StandingGateTile({ gate, detail }: { gate: string; detail?: GateDetail }) {
  // A gate the file does not carry is "not reported" — never a pass. Same rule
  // as the legacy board, for the same reason.
  const status = detail?.status ?? 'absent';
  const tone = STATUS_TONE[status] ?? {
    border: 'transparent',
    bg: 'transparent',
    text: '#7c8590',
    mark: status === 'absent' ? '—' : status.toUpperCase(),
  };
  const evidence = detail ? standingGateEvidence(gate, detail) : [];
  const advisory = detail ? campaignMeanAdvisory(detail) : null;

  return (
    <div
      className="flex flex-col gap-1.5 rounded-md border border-line bg-card px-3.5 py-3"
      style={
        tone.border === 'transparent' ? undefined : { borderColor: tone.border, background: tone.bg }
      }
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium text-ink">{STANDING_GATE_LABELS[gate] ?? gate}</span>
        <span
          className="font-mono text-[10px] font-semibold tracking-[.08em]"
          style={{ color: tone.text }}
        >
          {tone.mark}
        </span>
      </div>
      <div className="font-mono text-[9.5px] text-faint">
        {detail ? (STANDING_GATE_BLURBS[gate] ?? gate) : 'not reported by this gate file'}
      </div>
      {evidence.map((line) => (
        <div key={line} className="break-words font-mono text-[10px] leading-relaxed text-ink3">
          {line}
        </div>
      ))}
      {advisory !== null && (
        // Amber, and only amber: the tile itself keeps its PASS tint. An
        // advisory that read as a failure would be the cry-wolf alarm this
        // whole revision exists to remove.
        <div className="break-words rounded-md border border-warn/30 bg-warn/10 px-2 py-1.5 font-mono text-[10px] leading-relaxed text-warn">
          {advisory}
        </div>
      )}
    </div>
  );
}

/**
 * The standing-baseline board.
 *
 * Its subject is different from the legacy board's: there is no baseline RUN to
 * compare against, only the campaign's standing floor for this cell's regime
 * family, transcribed from the training journal. So the comparison table becomes
 * a single candidate column plus a floor, and the N-1 sibling — which used to be
 * the whole gate — is demoted to an explicitly informational panel.
 */
export function StandingGateBoard({ result }: { result: GateResult }) {
  const verdict = String(result.verdict ?? '');
  const tone = VERDICT_TONE[verdict] ?? {
    color: '#7c8590',
    label: verdict.toLowerCase(),
    sentence: 'This gate file carries a verdict this board has not been taught to explain.',
  };
  const details = result.gate_details ?? {};
  const gateKeys = [
    ...STANDING_GATE_NAMES,
    ...Object.keys(details).filter((g) => !STANDING_GATE_NAMES.includes(g as never)),
  ];
  const standing = result.standing_baseline_used;
  const sibling = result.sibling_comparison;
  const candidate = result.candidate_summary;

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-3">
            <span className="font-mono text-[13px] font-semibold text-ink">{result.version}</span>
            <Pill color={tone.color}>{verdict}</Pill>
            <span className="font-mono text-[9.5px] text-faint">
              family: {result.family ?? 'unresolved'}
              {standing?.family_source != null && standing.family_source !== ''
                ? ` (${standing.family_source})`
                : ''}
            </span>
            {result.resolved_latest && (
              <span className="font-mono text-[9.5px] text-warn">
                resolved as latest — no version was asked for; the API picked the most recently
                written data/*_gate_result.json
              </span>
            )}
          </div>
          <p
            className="rounded-md border px-3 py-2 text-[10.5px] leading-relaxed"
            style={{ borderColor: `${tone.color}4d`, background: `${tone.color}14`, color: tone.color }}
          >
            {tone.sentence}
          </p>
          {typeof result.error === 'string' && result.error !== '' && (
            <div className="break-words font-mono text-[10.5px] text-danger-tint">{result.error}</div>
          )}
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2 lg:grid-cols-3">
        {gateKeys.map((gate) => (
          <StandingGateTile key={gate} gate={gate} detail={details[gate]} />
        ))}
      </div>

      {result.failures.length > 0 && (
        <Card label="Failures">
          <div className="flex flex-col gap-1">
            {result.failures.map((f) => (
              <div key={f} className="break-words font-mono text-[10.5px] text-danger-tint">
                {f}
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card
        label="Standing baseline applied"
        right={<span className="font-mono text-[9.5px] text-faint">data/standing_baseline.json</span>}
      >
        {standing === undefined ? (
          <EmptyNote
            title="This gate file names no standing baseline"
            detail="The verdict is present but standing_baseline_used is not — the floor it was judged against cannot be shown."
          />
        ) : (
          <div className="flex flex-col gap-2">
            <Table head={['', 'Value']}>
              <tr className="border-b border-hair">
                <Txt className="font-mono text-ink3">Per-cell floor (the bar)</Txt>
                <Num className="text-ink2">
                  {typeof standing.per_cell_floor_usd === 'number'
                    ? signedUsd(standing.per_cell_floor_usd)
                    : '—'}
                </Num>
              </tr>
              <tr className="border-b border-hair">
                <Txt className="font-mono text-ink3">Campaign mean (advisory)</Txt>
                <Num className="text-ink3">
                  {typeof standing.campaign_mean_usd === 'number'
                    ? signedUsd(standing.campaign_mean_usd)
                    : '—'}
                </Num>
              </tr>
              <tr className="border-b border-hair">
                <Txt className="font-mono text-ink3">Candidate PnL</Txt>
                <Num className={pnlClass(candidate?.pnl)}>
                  {typeof candidate?.pnl === 'number' ? signedUsd(candidate.pnl) : '—'}
                </Num>
              </tr>
              <tr className="border-b border-hair">
                <Txt className="font-mono text-ink3">Trades</Txt>
                <Num className="text-ink2">
                  {typeof candidate?.trades === 'number' ? String(candidate.trades) : '—'}
                </Num>
              </tr>
              <tr className="last:border-0">
                <Txt className="font-mono text-ink3">Win rate</Txt>
                <Num className="text-ink2">
                  {typeof candidate?.win_rate === 'number' ? pct(candidate.win_rate) : '—'}
                </Num>
              </tr>
            </Table>
            <p className="text-[10px] leading-relaxed text-muted">
              The <span className="font-semibold">per-cell floor</span> is the bar: a cell that lost
              money fails, and nothing else does. The{' '}
              <span className="font-semibold">campaign mean</span> is the mean of this family&apos;s
              walk-forward window distribution, which is heavily skewed — crisis&apos;s median window
              is +$65 against its +$599 mean — so it is <em>not</em> a per-cell bar and never fails a
              run. Comparing against it honestly is a grid-level aggregation; that instrument is
              specified in <span className="font-mono">training_log/V247_RULER.md</span> and built in{' '}
              <span className="font-mono">omega/eval/grid_ruler.py</span>. When this run&apos;s grid
              has been ruled, its verdict is the campaign-ruler card below.
            </p>
            {standing.journal_cite != null && standing.journal_cite !== '' && (
              <p className="text-[10px] leading-relaxed text-muted">
                Cited from <span className="font-mono">{standing.journal_cite}</span>. These numbers
                are a journal act: they move only with a pre-registration, never to make a run pass.
              </p>
            )}
            {standing.source != null && standing.source !== '' && (
              <p className="break-words font-mono text-[9.5px] text-faint">{standing.source}</p>
            )}
          </div>
        )}
      </Card>

      {sibling !== undefined && (
        <Card label="N-1 sibling — informational only">
          <div className="flex flex-col gap-2">
            <p className="text-[10.5px] leading-relaxed text-muted">
              The sibling is <span className="font-semibold">not the gate</span>. It is here only to
              detect a run that reproduced a prior run instead of measuring something new — the
              failure mode that made 18 archived gate files read as a green board.
            </p>
            <Table head={['Metric', sibling.sibling_label ?? 'sibling', result.version, 'Δ']}>
              <tr className="border-b border-hair">
                <Txt className="font-mono text-ink3">PnL</Txt>
                <Num className="text-ink2">
                  {typeof sibling.sibling_pnl_usd === 'number' ? usd(sibling.sibling_pnl_usd) : '—'}
                </Num>
                <Num className={pnlClass(sibling.candidate_pnl_usd ?? undefined)}>
                  {typeof sibling.candidate_pnl_usd === 'number' ? usd(sibling.candidate_pnl_usd) : '—'}
                </Num>
                <Num className="text-ink3">
                  {typeof sibling.delta_pnl_usd === 'number' ? signedUsd(sibling.delta_pnl_usd) : '—'}
                </Num>
              </tr>
              <tr className="last:border-0">
                <Txt className="font-mono text-ink3">Trades</Txt>
                <Num className="text-ink2">
                  {typeof sibling.sibling_trades === 'number' ? String(sibling.sibling_trades) : '—'}
                </Num>
                <Num className="text-ink2">
                  {typeof sibling.candidate_trades === 'number' ? String(sibling.candidate_trades) : '—'}
                </Num>
                <Num className="text-ink3">—</Num>
              </tr>
            </Table>
            {sibling.identical_trade_fingerprint === true && (
              <p className="rounded-md border border-warn/30 bg-warn/10 px-3 py-2 text-[10.5px] leading-relaxed text-warn">
                Identical trade fingerprint (the timestamp column is dropped before hashing, so a
                bit-identical replay still matches): this run reproduced{' '}
                {sibling.sibling_label ?? 'its sibling'} exactly.
              </p>
            )}
          </div>
        </Card>
      )}

      {result.notes !== undefined && result.notes.length > 0 && (
        <Card label="Notes">
          <div className="flex flex-col gap-1">
            {result.notes.map((n) => (
              <div key={n} className="break-words font-mono text-[10px] leading-relaxed text-ink3">
                {n}
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

// ── Campaign ruler (omega/eval/grid_ruler.py, training_log/V247_RULER.md) ────
//
// The card the gate board could not draw until the grid ruler existed.
//
// Everything above judges ONE CELL against a $0 floor. This judges the WHOLE
// GRID against the STANDING BASELINE, on the only instrument V247_RULER.md says
// can carry that question: the paired per-window Δ over the 32 frozen
// walk-forward windows. §1 — "A verdict is a paired per-window Δ (ON − OFF)
// aggregated per regime" — and the OFF-arm LEVEL spread, the $27k one, "can
// never be the gate".
//
// It renders only when a grid verdict exists for the picked label, because one
// usually does not: `scripts/run_grid_ruler.py` is an end-of-grid tool run by
// hand and is deliberately not in the training loop.

/** Verdict → colour and the sentence that says what actually happened. */
export const GRID_VERDICT_TONE: Record<string, { color: string; label: string; sentence: string }> = {
  PASS: {
    color: '#4ec97a',
    label: 'baseline held',
    sentence:
      'No regime family regressed past its MDE. This is a NO-REGRESSION result, not a proof of improvement: the ruler asks whether the standing baseline went backwards, and the answer is no.',
  },
  FAIL: {
    color: '#e5675b',
    label: 'baseline regressed',
    sentence:
      'At least one family’s mean-Δ fell below −MDE — a regression large enough that this instrument can actually resolve it. The failing family’s own numbers are in its row.',
  },
  INSUFFICIENT_GRID: {
    color: '#e0a33a',
    label: 'insufficient grid',
    sentence:
      'The run did not cover the manifest, so the campaign question was never asked. This is NOT a pass. The missing window ids are named below; the MDE bars have been widened to the actual n so that any FAIL reported alongside is one this partial grid can genuinely support.',
  },
  ERROR: {
    color: '#e5675b',
    label: 'ruler error',
    sentence:
      'The ruler itself raised. This card is the record of that failure, rather than a silence.',
  },
};

/** Reading order: pooled last, because it is the row the doc calls decisive. */
const FAMILY_ORDER = ['crisis', 'recent', 'trend', 'pooled'];

/** What each family's bar is measured at, per V247_RULER.md §7. */
const FAMILY_BLURB: Record<string, string> = {
  crisis: 'n=12 windows · published MDE $1,565',
  recent: 'n=10 windows · published MDE $1,043',
  trend: 'n=10 windows · published MDE $4,118 — the worst-instrumented regime',
  pooled: 'n=32 windows · $1,425 median-sd, $875 low-coupling, $633 near-inert',
};

export interface RulerBar {
  family: string;
  status: string;
  n: number;
  expectedN: number | null;
  meanDelta: number | null;
  mde: number | null;
  margin: number | null;
  /**
   * `meanDelta / mde`, clamped to ±1.5 for drawing. Null when the family was not
   * evaluated — a family with no cells has no bar, and drawing a zero-length one
   * would read as "exactly on the baseline", which is a measurement it never made.
   */
  ratio: number | null;
  tone: 'pass' | 'fail' | 'within_noise' | 'not_evaluated';
  /** The numbers, as one assertable line. */
  evidence: string;
  ci: [number, number] | null;
}

/**
 * The bars, as data — pure, so the arithmetic and the tone rules are testable
 * without a DOM.
 *
 * The three-way tone is the doc's own trichotomy and collapsing it would lose
 * the point. A negative mean-Δ INSIDE the MDE is `within_noise`, not a failure:
 * §7 says claims below the threshold "may not be used as an acceptance bar or
 * reported as signal", so the honest rendering is amber prose, not a red bar.
 */
export function rulerBars(families: Record<string, GridFamilyRuling> | undefined): RulerBar[] {
  const all = families ?? {};
  const known = FAMILY_ORDER.filter((f) => f in all);
  const extra = Object.keys(all).filter((f) => !FAMILY_ORDER.includes(f)).sort();

  return [...known, ...extra].map((family) => {
    const r = all[family];
    const meanDelta = typeof r.mean_delta_usd === 'number' ? r.mean_delta_usd : null;
    const mde = typeof r.mde_usd === 'number' ? r.mde_usd : null;
    const margin = typeof r.margin_usd === 'number' ? r.margin_usd : null;
    const evaluated = r.status !== 'not_evaluated' && meanDelta !== null && mde !== null && mde > 0;

    let tone: RulerBar['tone'] = 'not_evaluated';
    if (evaluated) {
      if (r.status === 'fail') tone = 'fail';
      else if (meanDelta < 0) tone = 'within_noise';
      else tone = 'pass';
    }

    const ratio = evaluated ? Math.max(-1.5, Math.min(1.5, meanDelta / mde)) : null;

    const evidence = evaluated
      ? `mean-Δ ${signedUsd(meanDelta)} vs bar ${signedUsd(-mde)} (margin ${signedUsd(margin)})`
      : typeof r.reason === 'string' && r.reason !== ''
        ? r.reason
        : 'not evaluated — no covered windows in this family';

    const ci = Array.isArray(r.bootstrap_ci95_usd) && r.bootstrap_ci95_usd.length === 2
      ? ([r.bootstrap_ci95_usd[0], r.bootstrap_ci95_usd[1]] as [number, number])
      : null;

    return {
      family,
      status: r.status,
      n: r.n,
      expectedN: typeof r.expected_n === 'number' ? r.expected_n : null,
      meanDelta,
      mde,
      margin,
      ratio,
      tone,
      evidence,
      ci,
    };
  });
}

const BAR_TONE: Record<RulerBar['tone'], { color: string; mark: string }> = {
  pass: { color: '#4ec97a', mark: 'HELD' },
  fail: { color: '#e5675b', mark: 'REGRESSED' },
  within_noise: { color: '#e0a33a', mark: 'WITHIN NOISE' },
  not_evaluated: { color: '#7c8590', mark: 'NOT EVALUATED' },
};

/**
 * One family's Δ-vs-MDE bar.
 *
 * The track is centred on zero and the MDE floor sits at the left edge, so the
 * question the picture answers is exactly the question the ruler asks: how far
 * is the mean-Δ from the bar it would have to breach to count as a regression.
 */
function FamilyBar({ bar }: { bar: RulerBar }) {
  const tone = BAR_TONE[bar.tone];
  // Zero sits at the midpoint; ±1.5·MDE spans the track.
  const half = bar.ratio === null ? 0 : (Math.abs(bar.ratio) / 1.5) * 50;
  const left = bar.ratio === null ? 50 : bar.ratio < 0 ? 50 - half : 50;

  return (
    <div className="flex flex-col gap-1.5 rounded-md border border-line bg-card px-3.5 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-[11px] font-medium text-ink">{bar.family}</span>
        <span
          className="font-mono text-[10px] font-semibold tracking-[.08em]"
          style={{ color: tone.color }}
        >
          {tone.mark}
        </span>
      </div>
      <div className="font-mono text-[9.5px] text-faint">
        {bar.expectedN === null || bar.n === bar.expectedN
          ? (FAMILY_BLURB[bar.family] ?? `n=${String(bar.n)}`)
          : `${String(bar.n)}/${String(bar.expectedN)} windows — bar widened to the actual n`}
      </div>

      {/* The track. −MDE is the left edge, 0 the middle, +MDE the right. */}
      <div className="relative h-2 w-full rounded-sm border border-hair bg-control">
        {/* The bar itself, growing from the zero line. */}
        {bar.ratio !== null && (
          <div
            className="absolute top-0 h-full rounded-sm"
            style={{ left: `${String(left)}%`, width: `${String(Math.max(half, 0.8))}%`, background: tone.color }}
          />
        )}
        {/* The zero line — the standing baseline itself. */}
        <div className="absolute left-1/2 top-0 h-full w-px bg-ink3" />
        {/* The −MDE floor: the only line a family can fail by crossing. */}
        <div className="absolute left-[16.67%] top-0 h-full w-px" style={{ background: '#e5675b80' }} />
      </div>
      <div className="flex justify-between font-mono text-[8.5px] text-faint">
        <span>{bar.mde === null ? '' : `−MDE ${signedUsd(-bar.mde)}`}</span>
        <span>0 · standing baseline</span>
      </div>

      <div className="break-words font-mono text-[10px] leading-relaxed text-ink3">{bar.evidence}</div>
      {bar.ci !== null && (
        <div className="font-mono text-[9.5px] text-faint">
          bootstrap CI95 [{signedUsd(bar.ci[0])}, {signedUsd(bar.ci[1])}]
          {bar.ci[0] > 0 || bar.ci[1] < 0 ? '' : ' — contains zero'}
        </div>
      )}
      {bar.tone === 'within_noise' && (
        <div className="break-words rounded-md border border-warn/30 bg-warn/10 px-2 py-1.5 font-mono text-[10px] leading-relaxed text-warn">
          A regression this instrument cannot resolve. V247_RULER.md §7 forbids reading it as signal,
          so it is neither a failure nor a silence.
        </div>
      )}
    </div>
  );
}

/**
 * The campaign-ruler card.
 *
 * Exported separately from its fetch so it can be rendered against a real
 * verdict file in tests.
 */
export function CampaignRulerCard({ result }: { result: GridRulerResult }) {
  const verdict = String(result.verdict);
  const tone = GRID_VERDICT_TONE[verdict] ?? {
    color: '#7c8590',
    label: verdict.toLowerCase(),
    sentence: 'This verdict file carries a verdict this card has not been taught to explain.',
  };
  const bars = rulerBars(result.families);
  const coverage = result.coverage;
  const perFamily = coverage?.per_family ?? {};
  const missing = Object.entries(perFamily).filter(([, c]) => c.missing.length > 0);

  return (
    <Card
      label="Campaign ruler — the whole grid against the standing baseline"
      right={<span className="font-mono text-[9.5px] text-faint">/api/v1/training/grid-ruler</span>}
    >
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <span className="font-mono text-[13px] font-semibold text-ink">{result.run_label}</span>
          <Pill color={tone.color}>{verdict}</Pill>
          {coverage !== undefined && (
            <span className="font-mono text-[9.5px] text-faint">
              {String(coverage.covered_windows ?? 0)}/{String(coverage.expected_windows ?? 0)} manifest
              windows{coverage.pairing != null && coverage.pairing !== '' ? ` · ${coverage.pairing}` : ''}
            </span>
          )}
        </div>

        {result.resolved_prefix === true && (
          // Load-bearing: without this line a reader takes the GRID's verdict for
          // their CELL's, which is precisely the conflation the two-layer split
          // exists to prevent.
          <p className="rounded-md border border-warn/30 bg-warn/10 px-3 py-2 text-[10.5px] leading-relaxed text-warn">
            This is the verdict for the grid <span className="font-mono">{result.run_label}</span>, not
            for <span className="font-mono">{result.requested ?? 'the cell you picked'}</span>. A grid
            verdict covers all {String(coverage?.expected_windows ?? 32)} windows at once; the cell you
            picked is one of them, and its own per-cell gates are the board above.
          </p>
        )}

        <p
          className="rounded-md border px-3 py-2 text-[10.5px] leading-relaxed"
          style={{ borderColor: `${tone.color}4d`, background: `${tone.color}14`, color: tone.color }}
        >
          {tone.sentence}
        </p>

        {typeof result.error === 'string' && result.error !== '' && (
          <div className="break-words font-mono text-[10.5px] text-danger-tint">{result.error}</div>
        )}

        <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2">
          {bars.map((bar) => (
            <FamilyBar key={bar.family} bar={bar} />
          ))}
        </div>

        {result.failures.length > 0 && (
          <div className="flex flex-col gap-1">
            {result.failures.map((f) => (
              <div key={f} className="break-words font-mono text-[10.5px] text-danger-tint">
                {f}
              </div>
            ))}
          </div>
        )}

        {missing.length > 0 && (
          <div className="flex flex-col gap-1.5 rounded-md border border-warn/30 bg-warn/10 px-3 py-2">
            <span className="font-mono text-[10px] font-semibold text-warn">
              Manifest windows this run never covered
            </span>
            {missing.map(([family, c]) => (
              <div key={family} className="break-words font-mono text-[9.5px] leading-relaxed text-warn">
                {family} {String(c.covered)}/{String(c.expected)} — missing {c.missing.join(', ')}
              </div>
            ))}
          </div>
        )}

        {coverage?.unpairable_cells !== undefined && coverage.unpairable_cells.length > 0 && (
          <div className="flex flex-col gap-1">
            <span className="font-mono text-[10px] text-ink3">
              Cells excluded — they named no manifest window, so they were dropped rather than
              counted as zero:
            </span>
            {coverage.unpairable_cells.map((c) => (
              <div key={c.label} className="break-words font-mono text-[9.5px] leading-relaxed text-faint">
                {c.label}: {c.reason}
              </div>
            ))}
          </div>
        )}

        {result.ruler_notes !== undefined && result.ruler_notes.length > 0 && (
          // Every conservative interpretation the ruler made, in full. The card is
          // only as trustworthy as its choices are legible, so none are truncated.
          <div className="flex flex-col gap-1.5">
            <span className="font-mono text-[10px] text-ink3">Ruler notes</span>
            {result.ruler_notes.map((n) => (
              <div key={n} className="break-words font-mono text-[9.5px] leading-relaxed text-muted">
                {n}
              </div>
            ))}
          </div>
        )}

        <p className="text-[10px] leading-relaxed text-muted">
          The bar is one-sided and it is a <span className="font-semibold">no-regression floor</span>:
          a family fails iff its mean paired Δ falls below −MDE, where MDE = 2.80·sd/√n at 80% power
          and α=0.05. It is recomputed at the grid&apos;s actual n, so a short grid gets a wider bar.
          Passing does <em>not</em> mean the candidate improved — V247_RULER.md §5&apos;s anti-Goodhart
          guard keeps acceptance bars in each run&apos;s own pre-registration, so this ruler may not
          invent one. Spec:{' '}
          <span className="font-mono">training_log/V247_RULER.md</span> · producer{' '}
          <span className="font-mono">scripts/run_grid_ruler.py</span>.
        </p>
      </div>
    </Card>
  );
}

/**
 * The board itself, separated from the fetch so it can be rendered against a
 * fixture. Everything an operator reads is decided here.
 *
 * Dispatches on `verdict`: a file that carries one is a standing-gate file and
 * gets the standing board; a file that does not is one of the 280 archived
 * v49-shape files and renders exactly as it did before this dispatch existed.
 */
export function GateBoard({ result }: { result: GateResult }) {
  if (typeof result.verdict === 'string' && result.verdict !== '') {
    return <StandingGateBoard result={result} />;
  }
  return <LegacyGateBoard result={result} />;
}

function LegacyGateBoard({ result }: { result: GateResult }) {
  const baseline = result.baseline_summary;
  const candidate = result.candidate_summary;
  const rows = summaryRows(baseline, candidate);
  const identical = summariesIdentical(baseline, candidate);
  // The union of the six known gates and whatever else the file carries, so a
  // gate this shell has never heard of still gets a tile.
  const known: readonly string[] = GATE_NAMES;
  const gateKeys = [...known, ...Object.keys(result.gates).filter((g) => !known.includes(g))];
  const unclaimed = unclaimedFailures(result.failures, gateKeys);

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <div className="flex flex-wrap items-center gap-3">
          <span className="font-mono text-[13px] font-semibold text-ink">{result.version}</span>
          <Pill color={result.passed ? '#4ec97a' : '#e5675b'}>
            {result.passed ? 'gates passed' : 'gates failed'}
          </Pill>
          <span className="font-mono text-[9.5px] text-faint">
            {String(result.failures.length)} failure{result.failures.length === 1 ? '' : 's'}
          </span>
          {result.resolved_latest && (
            <span className="font-mono text-[9.5px] text-warn">
              resolved as latest — no version was asked for; the API picked the most
              recently written data/*_gate_result.json
            </span>
          )}
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2 lg:grid-cols-3">
        {gateKeys.map((gate) => (
          <GateTile
            key={gate}
            gate={gate}
            result={result.gates[gate]}
            failures={failuresForGate(result.failures, gate)}
          />
        ))}
      </div>

      {unclaimed.length > 0 && (
        <Card label="Failures not attributed to a gate">
          <div className="flex flex-col gap-1">
            {unclaimed.map((f) => (
              <div key={f} className="break-words font-mono text-[10.5px] text-danger-tint">
                {f}
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card
        label="Baseline vs candidate"
        right={<span className="font-mono text-[9.5px] text-faint">/api/v1/training/gates</span>}
      >
        {!baseline && !candidate ? (
          <EmptyNote
            title="This gate file carries no summaries"
            detail="The gates ran, but v48_summary / v49_summary are absent from the file — only the verdicts above are available."
          />
        ) : (
          <div className="flex flex-col gap-3">
            {identical && (
              <p className="rounded-md border border-warn/30 bg-warn/10 px-3 py-2 text-[10.5px] leading-relaxed text-warn">
                Both summaries carry <span className="font-semibold">identical measurements</span> —
                same PnL, trades, win rate, drawdown and per-regime PnL — under two different
                version names ({baseline?.version ?? '—'} and {candidate?.version ?? '—'}). Every
                delta below is therefore exactly zero because the run was gated against itself,
                not because it changed nothing. 19 of the gate files in omega&apos;s data
                directory are like this, including the most recent one.
              </p>
            )}
            <Table head={['Metric', baseline?.version ?? 'baseline', candidate?.version ?? 'candidate', 'Δ']}>
              {rows.map((row) => (
                <tr key={row.label} className="border-b border-hair last:border-0">
                  <Txt className="font-mono text-ink3">{row.label}</Txt>
                  <Num className="text-ink2">{formatValue(row.kind, row.baseline)}</Num>
                  <Num className={row.kind === 'usd' ? pnlClass(row.candidate) : 'text-ink2'}>
                    {formatValue(row.kind, row.candidate)}
                  </Num>
                  <Num className={deltaTone(row)}>{formatDelta(row)}</Num>
                </tr>
              ))}
            </Table>
          </div>
        )}
      </Card>
    </div>
  );
}

/**
 * A gate request that failed, said properly.
 *
 * The distinction this makes is the important one: **404 is not a red board**.
 * A version with no gate file is a version the gates never ran for, which is a
 * completely different situation from a version that failed them, and a view
 * that let a 404 look like a failure would teach an operator to distrust the
 * green ones too. The handler's own sentence is rendered (via `ErrorNote`,
 * which carries the body excerpt), then the producer is named.
 */
export function GateLoadFailure({
  error,
  version,
  onShowLatest,
}: {
  error: Error;
  /** Empty string means the latest was requested. */
  version: string;
  onShowLatest?: () => void;
}) {
  return (
    <>
      <ErrorNote error={error} what={`loading gates for ${version === '' ? 'the latest run' : version}`} />
      <p className="mt-3 text-[10.5px] leading-relaxed text-muted">
        A missing gate result is not a failed gate: it means the gates never ran for that label.{' '}
        <span className="font-mono">scripts/run_training.py</span> writes{' '}
        <span className="font-mono">data/&#123;version&#125;_gate_result.json</span> at the end of a
        run via <span className="font-mono">omega/eval/standing_gates.py</span> (before 2026-08-18,{' '}
        <span className="font-mono">omega/eval/v49_gates.py</span>). Since that repoint a file is
        written for <em>every</em> verdict, so a 404 on a recent label means the run itself never
        reached the end. Version labels are case-sensitive on the wire.
      </p>
      {version !== '' && onShowLatest && (
        <button
          type="button"
          onClick={onShowLatest}
          className="mt-3 rounded-md border border-line bg-control px-2.5 py-1.5 font-mono text-[10px] text-ink3 hover:text-ink"
        >
          show the latest gate result instead
        </button>
      )}
    </>
  );
}

export function VictoriaGates(_props: UseCaseViewProps) {
  // The selection lives in the shell-local store rather than in this component,
  // so the Journal's "open the gate board for this version" jump lands on the
  // right run — `onOpenView` carries a view id and nothing else. See `../store.ts`.
  const asked = useFocusVersion() ?? '';
  const state = useVictoriaGates(asked === '' ? null : asked);
  // The grid verdict for the picked label, if one exists. It is a SEPARATE
  // request on purpose: a 404 here is the ordinary case (the ruler is an
  // end-of-grid tool run by hand) and must never take the gate board down with
  // it. Only asked-for labels are looked up — see `useVictoriaGridRuler`.
  const ruler = useVictoriaGridRuler(asked === '' ? null : asked);

  return (
    <ViewFrame
      title="Gates"
      subtitle="The gates a finished training run is judged by. Since 2026-08-18 that is omega/eval/standing_gates.py, which carries an explicit verdict — PASS, FAIL, NO_OP, NO_BASELINE or ERROR. The per-cell bar is $0: a cell that lost money fails, and nothing else does. The journal's crisis +$599 / trend +$2,997 / recent +$30 are campaign MEANS of skewed walk-forward distributions (crisis's median window is +$65), so they are reported as an advisory on a passing cell rather than used as a per-cell bar. Archived files predating the repoint carry the older six-gate sibling comparison and are rendered as they were written."
      actions={
        <VersionPicker
          value={asked}
          onChange={(v) => { setFocusVersion(v === '' ? null : v); }}
          listId="victoria-gates-versions"
          placeholder="latest gate result"
          ariaLabel="Gate version"
        />
      }
    >
      {state.error ? (
        <Card>
          <GateLoadFailure error={state.error} version={asked} onShowLatest={() => { setFocusVersion(null); }} />
        </Card>
      ) : state.loading || state.data === null ? (
        <Card>
          <LoadingNote what="loading gate result" />
        </Card>
      ) : (
        <div className="flex flex-col gap-4">
          <GateBoard result={state.data} />
          {/* Absent unless this label's grid has actually been ruled. No empty
              state and no error tile: a missing grid verdict is the normal
              condition, and a card that shouted about it would be the cry-wolf
              alarm the gate board itself was rewritten to remove. */}
          {ruler.data !== null && <CampaignRulerCard result={ruler.data} />}
        </div>
      )}
    </ViewFrame>
  );
}
