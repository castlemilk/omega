/**
 * Live — a training run as it happens.
 *
 * Three sources, layered by how much they can be trusted:
 *
 *   1. `/api/v1/training/metrics` — the spine. Aggregates the `victoria_*`
 *      tables and null-fills every slice, so it answers 200 with
 *      `status: "idle"` on an unseeded database instead of failing.
 *   2. the SSE stream — the cycle counter, live. Both its frames are *named*
 *      (`connected`, `progress`), which is why `createDataSource().sse` grew an
 *      `events` option in UC-3; without it this panel would sit at "connecting"
 *      forever against a perfectly healthy stream.
 *   3. `/api/v1/training/progress` — enrichment only: PnL/win-rate history,
 *      regime, activity log. It is allowed to fail. The handler used to
 *      unmarshal `data/training_progress.json` into a struct while omega's own
 *      `run_training.py` wrote a JSON *array* there, and answered HTTP 500 on
 *      the real repo data; `loadProgress` now accepts both shapes, but the
 *      failure branch stays and is rendered in its own panel rather than taking
 *      the view down — the alternative, catching it and showing an idle run,
 *      would report a healthy system that is actually broken.
 *
 * ── Live is a claim, and it has to be earned ─────────────────────────────────
 * None of these three says "a run is happening" on its own. `status` is
 * **inferred from a file's mtime**: `loadProgress` labels the checkpoint array
 * `running` only while `data/training_progress.json` was written inside
 * `runningWindow` (10 minutes) and `complete` otherwise, and `/metrics` copies
 * that status through. So a record from a run that ended weeks ago arrives
 * looking exactly like a live one apart from that word — which is how this view
 * came to show `CYCLE 45 / 0` and a flat sparkline for a trainer that was not
 * running. `liveness()` is the one place that decides, and everything that would
 * read as live is behind it.
 */
import { ago, clock, Pill, StatusDot } from '@omega-harness/usecase-kit/ui';
import type { UseCaseViewProps } from '@omega-harness/usecase-kit';
import { Sparkline } from '../charts.js';
import type { TrainingMetrics, TrainingProgress } from '../client.js';
import { pct, pnlClass, regimeColor, signedUsd } from '../format.js';
import { useVictoriaLiveStream, useVictoriaMetrics, useVictoriaProgress } from '../hooks.js';
import { Async, Card, EmptyNote, ErrorNote, LoadingNote, Stat, ViewFrame } from './chrome.js';

/** The only status the omega API uses to mean "a run is going right now". */
export const RUNNING_STATUS = 'running';

export interface Liveness {
  live: boolean;
  /** Every reason the payload is not a live run, in the operator's words. */
  reasons: string[];
}

/**
 * Is this payload describing a run in progress, or a record of an old one?
 *
 * Three independent ways to fail, all of them observed on the real repo data
 * (2026-08-20: `status: "complete"`, cycle 45, total 0):
 *
 *   - the status the API inferred from the progress file's mtime is not
 *     `running`;
 *   - there is no cycle total, so "45 / 0" is a fraction with no denominator
 *     rather than a progress reading;
 *   - the counter is past the total, which no run in progress can be.
 *
 * All the reasons are collected rather than short-circuited: the empty state has
 * to say *why*, and "not running" and "and its numbers are incoherent" are two
 * different things to know.
 */
export function liveness(p: {
  status?: string;
  current_cycle?: number;
  total_cycles?: number;
}): Liveness {
  const status = p.status ?? '';
  const current = p.current_cycle ?? 0;
  const total = p.total_cycles ?? 0;
  const reasons: string[] = [];

  if (status !== RUNNING_STATUS) {
    reasons.push(
      status === ''
        ? 'the API reported no status at all'
        : `the API reports status “${status}”, not “running” — it infers that from data/training_progress.json's mtime, and the file has not been written in the last ten minutes`,
    );
  }
  if (total <= 0) {
    reasons.push(
      `the record carries no cycle total (total_cycles is ${String(total)}), so “${String(current)} / ${String(total)}” is not a progress reading`,
    );
  } else if (current > total) {
    reasons.push(
      `the cycle counter (${String(current)}) is past the recorded total (${String(total)})`,
    );
  }
  return { live: reasons.length === 0, reasons };
}

/**
 * Can this series be drawn as a trend?
 *
 * Two values are the minimum for a line at all (`Sparkline` already says "no
 * history" below that). The second clause is the one that matters here: a
 * series of identical values — in practice a column of exact zeros carried by a
 * stale record — draws a confident flat line that reads as a measured result of
 * "no change", when what it actually is is a column the writer never filled.
 * Saying how many points it holds and that they are all the same value is
 * strictly more information than the line was carrying.
 */
export function plottable(values: readonly number[]): boolean {
  return values.length >= 2 && values.some((v) => v !== values[0]);
}

function StreamPanel() {
  const stream = useVictoriaLiveStream();
  // Only read inside the non-empty branch below, so an index access is sound.
  const latest = stream.frames[0]?.frame;

  return (
    <Card
      label="Event stream"
      right={
        <span className="flex items-center gap-1.5 font-mono text-[9.5px] text-faint">
          <StatusDot status={stream.connected ? 'working' : 'waiting'} size={5} />
          {stream.connected ? 'connected' : 'connecting'}
        </span>
      }
    >
      {stream.error !== null && (
        <div className="mb-2.5 font-mono text-[10px] text-warn">{stream.error}</div>
      )}
      {stream.frames.length === 0 ? (
        <EmptyNote
          title={stream.connected ? 'Connected — no cycles yet' : 'Waiting for the stream'}
          detail="The omega API emits a progress frame every 5 seconds while a run is going. An idle trainer sends nothing after the greeting."
        />
      ) : (
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-3 gap-2.5">
            <Stat
              label="Cycle"
              value={`${String(latest.current_cycle ?? 0)} / ${String(latest.total_cycles ?? 0)}`}
            />
            <Stat label="Status" value={latest.status ?? '—'} />
            <Stat label="Frames" value={String(stream.frames.length)} hint="this session" />
          </div>
          <div className="flex max-h-44 flex-col gap-1 overflow-y-auto">
            {stream.frames.map((f, i) => (
              <div
                key={`${String(f.at)}-${String(i)}`}
                className="flex items-baseline gap-2 border-b border-hair pb-1 font-mono text-[10px] last:border-0"
              >
                <span className="text-ghost">{clock(new Date(f.at).toISOString())}</span>
                <span className="text-accent-dim">{f.name}</span>
                <span className="truncate text-ink3">
                  cycle {String(f.frame.current_cycle ?? 0)} · {f.frame.status ?? '—'}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

function ProgressPanel() {
  const progress = useVictoriaProgress();

  if (progress.loading) return <Card label="Run detail"><LoadingNote what="loading progress" /></Card>;

  if (progress.error) {
    return (
      <Card label="Run detail">
        <div className="flex flex-col gap-2.5">
          <ErrorNote error={progress.error} what="GET /api/v1/training/progress" />
          <p className="text-[10.5px] leading-relaxed text-muted">
            This is a known backend defect, not a Foreman one. The handler decodes{' '}
            <span className="font-mono">data/training_progress.json</span> into a struct,
            but omega&apos;s <span className="font-mono">run_training.py</span> writes a
            JSON array of per-cycle records to that path — so the endpoint 500s
            whenever a real run has been done. The panels above read{' '}
            <span className="font-mono">/metrics</span> and the event stream and are
            unaffected.
          </p>
        </div>
      </Card>
    );
  }

  const p = progress.data;
  if (!p) return null;
  return <ProgressDetail progress={p} />;
}

/**
 * Why a series is not drawn, in the terms of the series itself.
 *
 * Never "no data": the record may hold twenty points and still have nothing to
 * plot, and an operator who is told "no data" will go looking for a file that is
 * sitting right there, full of zeros.
 */
export function unplottableReason(
  values: readonly number[],
  format: (v: number) => string,
): string {
  if (values.length === 0) return 'nothing to plot — the record carries no points for this series';
  if (values.length === 1) return 'nothing to plot — one recorded point is not a trend';
  return `nothing to plot — all ${String(values.length)} recorded points are the same value (${format(values[0])})`;
}

function Series({
  label,
  values,
  color,
  format,
}: {
  label: string;
  values: readonly number[];
  color: string;
  format: (v: number) => string;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="font-mono text-[9.5px] uppercase tracking-[.08em] text-faint">{label}</span>
      {plottable(values) ? (
        <Sparkline values={values} width={300} height={40} color={color} label={label} />
      ) : (
        <p className="max-w-[40ch] font-mono text-[9.5px] leading-relaxed text-faint">
          {unplottableReason(values, format)}
        </p>
      )}
    </div>
  );
}

/**
 * The run's own progress record, separated from the fetch so both a live and a
 * stale payload render on a fixture.
 *
 * `now` is injectable for the same reason: "3d ago" is part of the sentence this
 * panel asserts, and a clock a test cannot fix is a sentence a test cannot read.
 */
export function ProgressDetail({
  progress: p,
  now = Date.now(),
}: {
  progress: TrainingProgress;
  now?: number;
}) {
  const state = liveness(p);
  const pnlSeries = (p.pnl_history ?? []).map((h) => h.pnl);
  const winSeries = (p.win_rate_history ?? []).map((h) => h.win_rate);
  const activity = (p.activity_log ?? []).slice(-24).reverse();
  const regime = p.current_regime?.name ?? '';
  // "unknown" is the literal regime run_training.py writes for a cycle it could
  // not classify, and the confidence beside it is a Go zero value the JSON always
  // emits — the pill used to read "unknown 0%", which is a measurement of nothing
  // dressed as one.
  const namedRegime = regime !== '' && regime.toLowerCase() !== 'unknown';
  const confidence = p.current_regime?.confidence;
  const runId = p.run_id ?? '';
  const startedAt = p.started_at ?? '';
  const current = p.current_cycle ?? 0;
  const total = p.total_cycles ?? 0;

  return (
    <Card
      label="Run detail"
      right={
        namedRegime ? (
          <Pill color={regimeColor(regime)}>
            {regime}
            {confidence != null && confidence > 0 ? ` ${pct(confidence, 0)}` : ''}
          </Pill>
        ) : (
          <span className="font-mono text-[9.5px] text-faint">
            {regime === '' ? 'no regime recorded' : 'regime not classified'}
          </span>
        )
      }
    >
      <div className="flex flex-col gap-3.5">
        {!state.live && (
          <EmptyNote
            title="No training run in progress"
            detail={
              <span className="flex flex-col gap-1.5 text-left">
                <span>
                  Last recorded progress: cycle <span className="font-mono">{String(current)}</span>
                  {total > 0 ? (
                    <> of <span className="font-mono">{String(total)}</span></>
                  ) : (
                    <> (the record carries no cycle total)</>
                  )}
                  ,{' '}
                  {runId !== '' ? (
                    <>run <span className="font-mono">{runId}</span></>
                  ) : (
                    <>
                      no run id — <span className="font-mono">run_training.py</span> writes a
                      checkpoint array, which has no <span className="font-mono">run_id</span> field
                    </>
                  )}
                  ,{' '}
                  {startedAt === ''
                    ? 'and no start timestamp'
                    : `first checkpoint ${ago(startedAt, now)}`}
                  .
                </span>
                {state.reasons.map((r) => (
                  <span key={r}>· {r}</span>
                ))}
                <span>
                  What is below is that record, not a run in flight. Start one with{' '}
                  <span className="font-mono">scripts/run_training.py</span>; finished runs are in
                  the Runs tab.
                </span>
              </span>
            }
          />
        )}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Series label="PnL by cycle" values={pnlSeries} color="#4ec97a" format={signedUsd} />
          <Series
            label="Win rate by cycle"
            values={winSeries}
            color="#5b9dff"
            format={(v) => pct(v)}
          />
        </div>

        {activity.length === 0 ? (
          <EmptyNote
            title="No activity logged for this run"
            detail="The progress record's activity_log is empty. The checkpoint array run_training.py writes carries per-cycle numbers but no log lines, so this list stays empty for every run stored in that shape."
          />
        ) : (
          <div className="flex max-h-56 flex-col gap-1 overflow-y-auto">
            {activity.map((a, i) => (
              <div
                key={`${String(a.cycle)}-${String(i)}`}
                className="flex items-baseline gap-2 border-b border-hair pb-1 font-mono text-[10px] last:border-0"
              >
                <span className="w-10 flex-none text-right text-ghost">#{String(a.cycle)}</span>
                <span className="w-14 flex-none text-accent-dim">{a.type}</span>
                <span className="text-ink3">{a.message}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}

/** The aggregate strip, separated from the fetch so both states render on a fixture. */
export function LiveMetrics({ metrics: m }: { metrics: TrainingMetrics }) {
  const state = liveness(m);
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
        <Stat
          label="Cycle"
          // A cycle counter is a *live* reading. With no run in flight there is
          // no such reading — the last recorded one is reported below, in a
          // sentence that can say what it is.
          value={state.live ? `${String(m.current_cycle)} / ${String(m.total_cycles)}` : '—'}
          hint={state.live ? m.status : 'no run in progress'}
        />
        <Stat
          label="Total PnL"
          value={signedUsd(m.total_pnl)}
          tone={pnlClass(m.total_pnl)}
          hint={`realised ${signedUsd(m.realised_pnl)}`}
        />
        <Stat label="Win rate" value={pct(m.win_rate)} hint={`${String(m.total_trades)} trades`} />
        <Stat
          label="Memory"
          value={String(m.memory_count.total)}
          hint={`${String(m.memory_count.episodic)} episodic · ${String(m.memory_count.semantic)} semantic`}
        />
      </div>

      {!state.live && (
        <Card>
          <EmptyNote
            title="No training run in progress"
            detail={
              <span className="flex flex-col gap-1.5 text-left">
                <span>The omega API is not reporting a run in flight:</span>
                {state.reasons.map((r) => (
                  <span key={r}>· {r}</span>
                ))}
                <span>
                  The three figures beside the cycle counter are database aggregates over{' '}
                  <span className="font-mono">{String(m.total_trades)}</span> trades in the victoria
                  tables — they are real, and they are not live. Start a run with{' '}
                  <span className="font-mono">scripts/run_training.py</span>; finished runs are in
                  the Runs tab.
                </span>
              </span>
            }
          />
        </Card>
      )}

      {m.signal_health.length > 0 && (
        <Card label="Signal health">
          <div className="flex flex-wrap gap-2">
            {m.signal_health.map((s) => (
              <Pill key={s.name}>
                {s.name} {s.value.toFixed(3)}
              </Pill>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

export function VictoriaLive(_props: UseCaseViewProps) {
  const metrics = useVictoriaMetrics();

  return (
    <ViewFrame
      title="Live"
      subtitle="A training run while it is running: the cycle counter off the event stream, aggregates off the database, and the run's own progress record."
    >
      <div className="flex flex-col gap-4">
        <Async state={metrics} what="loading training metrics">
          {(m) => <LiveMetrics metrics={m} />}
        </Async>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <StreamPanel />
          <ProgressPanel />
        </div>
      </div>
    </ViewFrame>
  );
}
