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
import { ChartLegend, Funnel, LineChart, RegimeStrip, type ChartMarker, type LineSeries } from '../charts.js';
import { pct, ratio, regimeColor, sideColor } from '../format.js';
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

// ── Regime timeline ──────────────────────────────────────────────────────────

/**
 * The regime per cycle, in cycle order.
 *
 * Read off the FIRST trace of each cycle: regime is per-cycle portfolio state
 * repeated onto every ticker row (see `contextOf`), so any row of the cycle
 * carries it. A cycle whose rows all lack a regime yields null and renders as
 * a gap band, not as its neighbour's regime.
 */
export function regimeByCycle(traces: readonly DecisionTrace[]): {
  cycles: number[];
  regimes: (string | null)[];
} {
  const byCycle = new Map<number, string | null>();
  for (const t of traces) {
    if (typeof t.cycle !== 'number') continue;
    if (!byCycle.has(t.cycle)) byCycle.set(t.cycle, t.regime ?? null);
  }
  const cycles = [...byCycle.keys()].sort((a, b) => a - b);
  return { cycles, regimes: cycles.map((c) => byCycle.get(c) ?? null) };
}

export interface RegimeAggregate {
  regime: string | null;
  cycles: number;
  evaluated: number;
  proposed: number;
  traded: number;
}

/** Funnel counts per regime — where each regime's decisions actually went. */
export function regimeAggregates(traces: readonly DecisionTrace[]): RegimeAggregate[] {
  const byRegime = new Map<string | null, { cycleSet: Set<number>; rows: DecisionTrace[] }>();
  for (const t of traces) {
    const key = t.regime ?? null;
    const entry = byRegime.get(key) ?? { cycleSet: new Set<number>(), rows: [] };
    if (typeof t.cycle === 'number') entry.cycleSet.add(t.cycle);
    entry.rows.push(t);
    byRegime.set(key, entry);
  }
  return [...byRegime]
    .map(([regime, { cycleSet, rows }]) => {
      const counts = funnelCounts(rows);
      return {
        regime,
        cycles: cycleSet.size,
        evaluated: counts.evaluated,
        proposed: counts.proposed,
        traded: counts.traded,
      };
    })
    .sort((a, b) => b.evaluated - a.evaluated);
}

// ── Conviction vs thresholds ─────────────────────────────────────────────────

/** Distinct tickers in the traces, alphabetical. */
export function tickersOf(traces: readonly DecisionTrace[]): string[] {
  const seen = new Set<string>();
  for (const t of traces) if (t.ticker != null && t.ticker !== '') seen.add(t.ticker);
  return [...seen].sort((a, b) => a.localeCompare(b));
}

export interface ThresholdSeries {
  cycles: number[];
  regimes: (string | null)[];
  conviction: number[];
  longThresh: number[];
  /** short_thresh NEGATED: shorts gate on |conviction| ≥ short_thresh with a
   *  negative conviction, so the bar the line has to cross sits below zero. */
  shortThreshMirrored: number[];
  markers: ChartMarker[];
  /** Rows for this ticker that carry no weighted_conviction — not drawn. */
  dropped: number;
}

/**
 * One ticker's conviction against the regime-adaptive thresholds, per cycle.
 *
 * Only rows with a `weighted_conviction` are plotted — absent means the value
 * was never computed (honesty rule 3), and drawing it as 0 would invent a flat
 * conviction. The count of dropped rows is returned so the view can say so.
 * Markers sit where `final_decision` was TRADE, coloured by the proposed side.
 */
export function tickerThresholdSeries(
  traces: readonly DecisionTrace[],
  ticker: string,
): ThresholdSeries {
  const rows = traces
    .filter((t) => t.ticker === ticker && typeof t.cycle === 'number')
    .sort((a, b) => (a.cycle ?? 0) - (b.cycle ?? 0));
  const plotted = rows.filter((t) => typeof t.weighted_conviction === 'number');
  const markers: ChartMarker[] = [];
  plotted.forEach((t, i) => {
    if ((t.final_decision ?? '').toUpperCase() === 'TRADE') {
      markers.push({
        index: i,
        value: t.weighted_conviction ?? 0,
        color: sideColor(t.proposal),
        label: `cycle ${String(t.cycle ?? '—')}: ${t.proposal ?? 'TRADE'} at ${ratio(t.weighted_conviction, 4)}`,
      });
    }
  });
  return {
    cycles: plotted.map((t) => t.cycle ?? 0),
    regimes: plotted.map((t) => t.regime ?? null),
    conviction: plotted.map((t) => t.weighted_conviction ?? 0),
    longThresh: plotted.map((t) => t.long_thresh ?? 0),
    shortThreshMirrored: plotted.map((t) => -(t.short_thresh ?? 0)),
    markers,
    dropped: rows.length - plotted.length,
  };
}

function DecisionPill({ decision }: { decision: string | undefined }) {
  const d = (decision ?? '').toUpperCase();
  const color = d === 'TRADE' ? '#4ec97a' : d === 'FILTERED' ? '#e5c04a' : '#6b6b74';
  return <Pill color={color}>{d === '' ? '—' : d}</Pill>;
}

/** The regime timeline: bands over the loaded cycles plus per-regime funnels. */
export function RegimeTimeline({ traces }: { traces: readonly DecisionTrace[] }) {
  const { cycles, regimes } = useMemo(() => regimeByCycle(traces), [traces]);
  const aggregates = useMemo(() => regimeAggregates(traces), [traces]);
  if (cycles.length === 0) {
    return (
      <EmptyNote
        title="No cycle numbers in these traces"
        detail="Every loaded trace lacks a cycle field, so there is no timeline to band."
      />
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <RegimeStrip regimes={regimes} padLeft={0} padRight={0} height={20} colorOf={regimeColor} />
      <div className="flex items-center justify-between font-mono text-[9.5px] text-faint">
        <span>cycle {String(cycles[0])}</span>
        <span>
          {[...new Set(regimes.filter((r): r is string => r !== null))].map((r) => (
            <span key={r} className="ml-3 inline-flex items-center gap-1">
              <span className="inline-block h-2 w-2 rounded-[2px]" style={{ background: regimeColor(r) }} />
              {r}
            </span>
          ))}
        </span>
        <span>cycle {String(cycles[cycles.length - 1])}</span>
      </div>
      <Table head={['Regime', 'Cycles', 'Evaluated', 'Proposed', 'Traded', 'Conversion']}>
        {aggregates.map((a) => (
          <tr key={a.regime ?? 'unlabelled'} className="border-b border-hair last:border-0">
            <Txt className="font-mono font-medium" >
              <span className="flex items-center gap-2">
                <span
                  className="inline-block h-2 w-2 flex-none rounded-[2px]"
                  style={{ background: a.regime === null ? 'rgba(255,255,255,.12)' : regimeColor(a.regime) }}
                />
                <span className="text-ink">{a.regime ?? 'no regime recorded'}</span>
              </span>
            </Txt>
            <Num className="text-ink3">{String(a.cycles)}</Num>
            <Num className="text-ink3">{String(a.evaluated)}</Num>
            <Num className="text-ink2">{String(a.proposed)}</Num>
            <Num className={a.traded > 0 ? 'text-ok' : 'text-ink3'}>{String(a.traded)}</Num>
            <Num className="text-ink3">{a.evaluated > 0 ? pct(a.traded / a.evaluated) : '—'}</Num>
          </tr>
        ))}
      </Table>
    </div>
  );
}

/** One ticker's conviction line against the bars it had to clear. */
export function ThresholdBands({
  traces,
  ticker,
}: {
  traces: readonly DecisionTrace[];
  ticker: string;
}) {
  const s = useMemo(() => tickerThresholdSeries(traces, ticker), [traces, ticker]);
  if (s.cycles.length < 2) {
    return (
      <EmptyNote
        title={`Not enough plotted cycles for ${ticker}`}
        detail={
          s.dropped > 0
            ? `${String(s.dropped)} of this ticker's rows carry no weighted_conviction, and fewer than two remain to draw a line through.`
            : 'Fewer than two cycles with a conviction value — nothing to draw a line through.'
        }
      />
    );
  }
  const series: LineSeries[] = [
    { values: s.conviction, color: 'var(--uc-accent)', label: 'weighted conviction' },
    { values: s.longThresh, color: '#4ec97a', label: 'long threshold', dashed: true },
    { values: s.shortThreshMirrored, color: '#e5675b', label: 'short threshold (mirrored below zero)', dashed: true },
  ];
  return (
    <div className="flex flex-col gap-2">
      <LineChart
        series={series}
        height={200}
        markers={s.markers}
        xLabels={s.cycles.map((c) => `cycle ${String(c)}`)}
        formatY={(v) => v.toFixed(2)}
        tickCount={4}
      />
      <RegimeStrip regimes={s.regimes} height={12} colorOf={regimeColor} />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <ChartLegend series={series} />
        <span className="font-mono text-[9.5px] text-faint">
          {String(s.markers.length)} trade{s.markers.length === 1 ? '' : 's'} marked
          {s.dropped > 0 ? ` · ${String(s.dropped)} rows without a conviction value not drawn` : ''}
        </span>
      </div>
      <p className="text-[10.5px] leading-relaxed text-muted">
        A long fires when the conviction line crosses the upper dashed bar; a short when it
        crosses the lower one (shorts gate on |conviction| against{' '}
        <span className="font-mono">short_thresh</span>, so the bar is drawn mirrored below
        zero). The bars move because the thresholds are regime-adaptive — the strip underneath
        shows which regime set them.
      </p>
    </div>
  );
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
  const tickers = useMemo(() => tickersOf(traces), [traces]);
  const [pickedTicker, setPickedTicker] = useState('');
  const ticker = pickedTicker !== '' && tickers.includes(pickedTicker) ? pickedTicker : tickers[0] ?? '';

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

      <Card
        label="Regime timeline"
        right={
          <span className="font-mono text-[9.5px] text-faint">
            all loaded cycles — regime is per-cycle state, so the cycle filter above does not apply
          </span>
        }
      >
        <RegimeTimeline traces={traces} />
      </Card>

      <Card
        label={ticker === '' ? 'Conviction vs thresholds' : `Conviction vs thresholds · ${ticker}`}
        right={
          tickers.length > 0 ? (
            <span className="flex items-center gap-2">
              <label htmlFor="victoria-conviction-ticker" className="font-mono text-[9.5px] text-faint">
                ticker
              </label>
              <select
                id="victoria-conviction-ticker"
                value={ticker}
                onChange={(e) => { setPickedTicker(e.target.value); }}
                className="rounded-md border border-line bg-control px-2 py-1 font-mono text-[10px] text-ink focus:border-edge focus:outline-none"
              >
                {tickers.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </span>
          ) : undefined
        }
      >
        {ticker === '' ? (
          <EmptyNote
            title="No tickers in these traces"
            detail="Every loaded trace lacks a ticker field, so there is nothing to plot a conviction line for."
          />
        ) : (
          <ThresholdBands traces={traces} ticker={ticker} />
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
