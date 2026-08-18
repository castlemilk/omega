/**
 * Gates — the ship/no-ship board.
 *
 * `omega/eval/v49_gates.py` runs six hard gates over every training run and
 * writes `data/{version}_gate_result.json`. That file, and only that file,
 * decides whether a run is allowed to become the new baseline. This view is that
 * decision, rendered: six tiles, the failure strings underneath the ones that
 * failed, and the baseline-vs-candidate numbers the gates were computed from.
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
import { GATE_NAMES, type GateResult, type GateSummary } from '../client.js';
import { pct, pnlClass, signedUsd, usd } from '../format.js';
import { useVictoriaGates } from '../hooks.js';
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

/**
 * The board itself, separated from the fetch so it can be rendered against a
 * fixture. Everything an operator reads is decided here.
 */
export function GateBoard({ result }: { result: GateResult }) {
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
        run via <span className="font-mono">omega/eval/v49_gates.py</span>. Version labels are
        case-sensitive on the wire.
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

  return (
    <ViewFrame
      title="Gates"
      subtitle="The six hard gates omega/eval/v49_gates.py runs over a training run. All six must pass for the run to become the new baseline — this is the ship/no-ship decision, not a summary of it."
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
        <GateBoard result={state.data} />
      )}
    </ViewFrame>
  );
}
