/**
 * Conviction — the funnel that turns “we looked at it” into “we traded it”.
 *
 * Victoria evaluates every ticker on every cycle, proposes a side when the
 * composite clears a regime-adaptive threshold, and then runs the proposal
 * through the filter pipeline (time filter → agreement ratio → weighted
 * conviction → regime/vol gate). Most of what the strategy *wanted* to do never
 * happens, and until this view there was nowhere to see where it went.
 *
 * The source is `/api/v1/training/decision-traces`, whose rows are per **ticker
 * per cycle** — 770 rows in `bt_v132a_crisis` is 7 tickers × 110 cycles, not 770
 * decisions about a portfolio. Three fields carry the funnel:
 *
 *   `proposal`        NONE | LONG | SHORT   — what the strategy wanted
 *   `final_decision`  HOLD | FILTERED | TRADE — what it got
 *   `blocking_filter` the named filter that stopped it, "" when none did
 *
 * The two drop-offs mean different things and are labelled differently: a HOLD
 * is the strategy declining to propose (the composite never cleared the bar), a
 * FILTERED is a proposal the pipeline killed. Collapsing them into one "didn't
 * trade" number is the mistake this view exists to avoid — they point at
 * different code.
 */
import { useMemo, useState } from 'react';
import { Pill } from '@omega-harness/usecase-kit/ui';
import type { UseCaseViewProps } from '@omega-harness/usecase-kit';
import { DECISION_TRACE_LIMIT, type DecisionTrace } from '../client.js';
import { Funnel } from '../charts.js';
import { pct, ratio, regimeColor } from '../format.js';
import { useVictoriaDecisionTraces } from '../hooks.js';
import { setFocusVersion, useFocusVersion } from '../store.js';
import { Async, Card, EmptyNote, Num, Stat, Table, Txt, ViewFrame } from './chrome.js';
import { VersionPicker } from './VersionPicker.js';

/** A proposal is anything that is not the writer's explicit "NONE". */
export function isProposal(trace: DecisionTrace): boolean {
  const p = (trace.proposal ?? '').toUpperCase();
  return p !== '' && p !== 'NONE';
}

export interface FunnelCounts {
  evaluated: number;
  proposed: number;
  traded: number;
  /** Evaluated but never proposed — the composite did not clear the threshold. */
  held: number;
  /** Proposed and then killed by a filter. */
  filtered: number;
  long: number;
  short: number;
}

/**
 * The funnel, counted.
 *
 * `held` and `filtered` are derived by subtraction rather than read off
 * `final_decision`, so the three funnel steps are guaranteed to be consistent
 * with each other. Where the writer disagrees with itself — a row proposing
 * nothing yet decided TRADE — the discrepancy shows up as a mismatch against
 * `decisionCounts`, which the view renders beside it rather than hiding.
 */
export function funnelCounts(traces: readonly DecisionTrace[]): FunnelCounts {
  let proposed = 0;
  let traded = 0;
  let long = 0;
  let short = 0;
  for (const t of traces) {
    if (isProposal(t)) {
      proposed++;
      if ((t.proposal ?? '').toUpperCase() === 'LONG') long++;
      else if ((t.proposal ?? '').toUpperCase() === 'SHORT') short++;
    }
    if ((t.final_decision ?? '').toUpperCase() === 'TRADE') traded++;
  }
  return {
    evaluated: traces.length,
    proposed,
    traded,
    held: traces.length - proposed,
    filtered: proposed - traded,
    long,
    short,
  };
}

/** Every `final_decision` value seen, with its count — the writer's own tally. */
export function decisionCounts(traces: readonly DecisionTrace[]): { decision: string; count: number }[] {
  const tally = new Map<string, number>();
  for (const t of traces) {
    const key = (t.final_decision ?? '').toUpperCase() || 'unlabelled';
    tally.set(key, (tally.get(key) ?? 0) + 1);
  }
  return [...tally].map(([decision, count]) => ({ decision, count })).sort((a, b) => b.count - a.count);
}

/**
 * Which filters did the killing, most first.
 *
 * Counted over every row that carries a blocking filter, not only over
 * proposals: `blacklist` blocks a ticker *before* a proposal exists (560 of 770
 * rows in the real file), and dropping those would make the biggest single
 * reason a run sat out invisible.
 */
export function blockingBreakdown(
  traces: readonly DecisionTrace[],
): { filter: string; count: number; blockedProposals: number }[] {
  const tally = new Map<string, { count: number; blockedProposals: number }>();
  for (const t of traces) {
    const filter = t.blocking_filter ?? '';
    if (filter === '') continue;
    const row = tally.get(filter) ?? { count: 0, blockedProposals: 0 };
    row.count++;
    if (isProposal(t) && (t.final_decision ?? '').toUpperCase() !== 'TRADE') row.blockedProposals++;
    tally.set(filter, row);
  }
  return [...tally]
    .map(([filter, v]) => ({ filter, ...v }))
    .sort((a, b) => b.count - a.count || a.filter.localeCompare(b.filter));
}

/** The cycles present in the loaded traces, ascending. */
export function cyclesOf(traces: readonly DecisionTrace[]): number[] {
  const seen = new Set<number>();
  for (const t of traces) if (typeof t.cycle === 'number') seen.add(t.cycle);
  return [...seen].sort((a, b) => a - b);
}

/**
 * The regime context for a selection.
 *
 * Read off the first row rather than averaged: these fields are per-cycle
 * portfolio state repeated onto every ticker row, so the mean of 7 identical
 * numbers is the number, and the mean *across* cycles would be a regime that
 * never happened. When a selection spans cycles the view says which cycle the
 * context came from.
 */
export function contextOf(traces: readonly DecisionTrace[]): DecisionTrace | null {
  return traces.length > 0 ? traces[0] : null;
}

function DecisionPill({ decision }: { decision: string | undefined }) {
  const d = (decision ?? '').toUpperCase();
  const color = d === 'TRADE' ? '#4ec97a' : d === 'FILTERED' ? '#e5c04a' : '#6b6b74';
  return <Pill color={color}>{d === '' ? '—' : d}</Pill>;
}

/** The funnel and its tables, separated from the fetch so it renders on a fixture. */
export function ConvictionFunnel({
  traces,
  version,
  truncated,
  cycle,
  onCycle,
}: {
  traces: readonly DecisionTrace[];
  version: string;
  truncated: boolean;
  /** null means "every loaded cycle". */
  cycle: number | null;
  onCycle?: (cycle: number | null) => void;
}) {
  const cycles = useMemo(() => cyclesOf(traces), [traces]);
  const selected = useMemo(
    () => (cycle === null ? traces : traces.filter((t) => t.cycle === cycle)),
    [traces, cycle],
  );
  const counts = funnelCounts(selected);
  const decisions = decisionCounts(selected);
  const blocking = blockingBreakdown(selected);
  const context = contextOf(selected);

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
        <Stat label="Evaluated" value={String(counts.evaluated)} hint={`${String(cycles.length)} cycles loaded`} />
        <Stat
          label="Proposed"
          value={String(counts.proposed)}
          hint={`${String(counts.long)} long · ${String(counts.short)} short`}
        />
        <Stat label="Traded" value={String(counts.traded)} tone="text-ok" />
        <Stat
          label="Conversion"
          value={counts.evaluated > 0 ? pct(counts.traded / counts.evaluated) : '—'}
          hint="traded ÷ evaluated"
        />
      </div>

      <Card
        label={cycle === null ? `Funnel · all ${String(cycles.length)} loaded cycles` : `Funnel · cycle ${String(cycle)}`}
        right={
          <span className="font-mono text-[9.5px] text-faint">
            {version} · /api/v1/training/decision-traces
          </span>
        }
      >
        <Funnel
          steps={[
            { label: 'Evaluated', count: counts.evaluated },
            { label: 'Proposed', count: counts.proposed, note: `${String(counts.held)} held — composite never cleared the threshold` },
            { label: 'Traded', count: counts.traded, note: `${String(counts.filtered)} filtered — a proposal the pipeline killed` },
          ]}
        />
        {truncated && (
          <p className="mt-3 text-[10.5px] leading-relaxed text-warn-tint">
            The API returned exactly as many rows as were asked for, so this run&apos;s trace file
            is longer than what is drawn here. These counts describe the first{' '}
            {String(traces.length)} traces, not the whole run.
          </p>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card label="Where they stopped">
          {blocking.length === 0 ? (
            <EmptyNote
              title="No blocking filter recorded"
              detail="Every loaded trace carries an empty blocking_filter — nothing was stopped by a named filter in this selection."
            />
          ) : (
            <Table head={['Blocking filter', 'Rows', 'Killed proposals']}>
              {blocking.slice(0, 12).map((b) => (
                <tr key={b.filter} className="border-b border-hair last:border-0">
                  <Txt className="font-mono text-ink2">{b.filter}</Txt>
                  <Num className="text-ink3">{String(b.count)}</Num>
                  <Num className={b.blockedProposals > 0 ? 'text-warn' : 'text-ink3'}>
                    {String(b.blockedProposals)}
                  </Num>
                </tr>
              ))}
            </Table>
          )}
        </Card>

        <Card label="Regime & threshold context">
          {context === null ? (
            <EmptyNote title="No context" detail="The selection holds no traces." />
          ) : (
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <Pill color={regimeColor(context.regime)}>{context.regime ?? 'unknown'}</Pill>
                <span className="font-mono text-[9.5px] text-faint">
                  as of cycle {String(context.cycle ?? '—')}
                  {cycle === null ? ' — the first loaded cycle; regime moves during a run' : ''}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-2 font-mono text-[10.5px] md:grid-cols-3">
                {[
                  ['bear prob', ratio(context.bear_prob, 4)],
                  ['bull prob', ratio(context.bull_prob, 4)],
                  ['thresh scale', ratio(context.thresh_scale, 4)],
                  ['long thresh', ratio(context.long_thresh, 4)],
                  ['short thresh', ratio(context.short_thresh, 4)],
                  ['abs min conviction', ratio(context.abs_min_conviction, 4)],
                ].map(([label, value]) => (
                  <div key={label} className="flex flex-col gap-0.5">
                    <span className="text-[9.5px] uppercase tracking-[.08em] text-faint">{label}</span>
                    <span className="text-ink2 tabular-nums">{value}</span>
                  </div>
                ))}
              </div>
              <p className="text-[10.5px] leading-relaxed text-muted">
                A cycle&apos;s own sit-out reason is written to the training checkpoint stream
                (<span className="font-mono">sit_out_reason</span> in{' '}
                <span className="font-mono">data/&#123;version&#125;_progress.json</span>), not to
                the decision traces. What is here is the per-ticker reason each candidate stopped,
                which is the finer-grained answer.
              </p>
            </div>
          )}
        </Card>
      </div>

      <Card
        label={`Decisions ${cycle === null ? 'across the loaded cycles' : `· cycle ${String(cycle)}`}`}
        right={
          onCycle ? (
            <span className="flex items-center gap-2">
              <label htmlFor="victoria-conviction-cycle" className="font-mono text-[9.5px] text-faint">
                cycle
              </label>
              <select
                id="victoria-conviction-cycle"
                value={cycle === null ? '' : String(cycle)}
                onChange={(e) => { onCycle(e.target.value === '' ? null : Number(e.target.value)); }}
                className="rounded-md border border-line bg-control px-2 py-1 font-mono text-[10px] text-ink focus:border-edge focus:outline-none"
              >
                <option value="">all loaded</option>
                {cycles.map((c) => (
                  <option key={c} value={String(c)}>
                    {String(c)}
                  </option>
                ))}
              </select>
            </span>
          ) : (
            <span className="font-mono text-[9.5px] text-faint">
              {String(decisions.map((d) => d.count).reduce((a, b) => a + b, 0))} rows
            </span>
          )
        }
      >
        {selected.length === 0 ? (
          <EmptyNote title="No traces in this selection" />
        ) : (
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2 font-mono text-[9.5px] text-faint">
              {decisions.map((d) => (
                <span key={d.decision}>
                  {d.decision} {String(d.count)}
                </span>
              ))}
            </div>
            <Table
              head={['Ticker', 'Composite', 'Conviction', 'Long thr', 'Short thr', 'Gap', 'Proposal', 'Blocked by', 'Decision']}
            >
              {selected.slice(0, 200).map((t, i) => (
                <tr key={`${t.ticker ?? ''}-${String(t.cycle ?? 0)}-${String(i)}`} className="border-b border-hair last:border-0">
                  <Txt className="font-mono font-medium text-ink">
                    {t.ticker ?? '—'}
                    {cycle === null && (
                      <span className="ml-1.5 text-faint">c{String(t.cycle ?? '—')}</span>
                    )}
                  </Txt>
                  <Num className="text-ink2">{ratio(t.raw_composite, 4)}</Num>
                  <Num className="text-ink2">{ratio(t.weighted_conviction, 4)}</Num>
                  <Num className="text-ink3">{ratio(t.long_thresh, 4)}</Num>
                  <Num className="text-ink3">{ratio(t.short_thresh, 4)}</Num>
                  <Num className="text-ink3">{ratio(t.threshold_gap, 4)}</Num>
                  <Num className="text-ink2">{t.proposal ?? '—'}</Num>
                  <Num className="text-ink3">{t.blocking_filter === '' || t.blocking_filter === undefined ? '—' : t.blocking_filter}</Num>
                  <td className="whitespace-nowrap px-2.5 py-1.5 text-right">
                    <DecisionPill decision={t.final_decision} />
                  </td>
                </tr>
              ))}
            </Table>
            {selected.length > 200 && (
              <p className="font-mono text-[9.5px] text-faint">
                showing the first 200 of {String(selected.length)} rows — pick a cycle to narrow it
              </p>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}

/**
 * The empty state, which has to name the producing side.
 *
 * A missing trace file is a **200 with zero rows**, not a 404 — so without this
 * copy the panel would be indistinguishable from a run that genuinely evaluated
 * nothing. Naming the writer is what turns "empty" into an action.
 */
export function NoDecisionTraces({ version }: { version: string }) {
  return (
    <EmptyNote
      title={`No decision traces for ${version}`}
      detail={
        <>
          The API answered 200 with zero traces, which is what it does when{' '}
          <span className="font-mono">data/decision_traces/{version}.jsonl</span> does not exist —
          this is an empty state, not a failure. The producer is the trainer:{' '}
          <span className="font-mono">scripts/run_training.py</span> writes a row per ticker per
          cycle while a run is in flight. Not every run in the version ledger has one.
        </>
      }
    />
  );
}

export function VictoriaConviction(_props: UseCaseViewProps) {
  // Shares the shell-local version focus with Gates and Journal; see `../store.ts`.
  const version = useFocusVersion() ?? '';
  const state = useVictoriaDecisionTraces(version === '' ? null : version);
  // The selected cycle is scoped to the version it was chosen in: cycle 7 of one
  // run is not cycle 7 of another, and carrying it across would silently show a
  // different run's cycle under the same number.
  const [selection, setSelection] = useState<{ version: string; cycle: number | null }>({
    version,
    cycle: null,
  });
  const cycle = selection.version === version ? selection.cycle : null;

  return (
    <ViewFrame
      title="Conviction"
      subtitle="Every ticker Victoria looked at, what it wanted to do, and which filter stopped it. A HOLD is the strategy declining to propose; a FILTERED is a proposal the pipeline killed — they point at different code."
      actions={
        <VersionPicker
          value={version}
          onChange={(v) => { setFocusVersion(v === '' ? null : v); }}
          listId="victoria-conviction-versions"
          placeholder="version with traces…"
          ariaLabel="Decision-trace version"
        />
      }
    >
      {version === '' ? (
        <Card>
          <EmptyNote
            title="Pick a version"
            detail="Decision traces are per-version. scripts/run_training.py writes one JSONL row per ticker per cycle to data/decision_traces/{version}.jsonl during a run; the API needs a version to find one."
          />
        </Card>
      ) : (
        <Async state={state} what={`loading decision traces for ${version}`}>
          {(data) =>
            data === null || data.traces.length === 0 ? (
              <Card>
                <NoDecisionTraces version={version} />
              </Card>
            ) : (
              <ConvictionFunnel
                traces={data.traces}
                version={version}
                truncated={data.total >= DECISION_TRACE_LIMIT}
                cycle={cycle}
                onCycle={(next) => { setSelection({ version, cycle: next }); }}
              />
            )
          }
        </Async>
      )}
    </ViewFrame>
  );
}
