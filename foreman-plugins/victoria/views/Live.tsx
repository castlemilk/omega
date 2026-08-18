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
 *      regime, activity log. It is **expected to fail**. The handler unmarshals
 *      `data/training_progress.json` into a struct while omega's own
 *      `run_training.py` writes a JSON *array* there, so it answers HTTP 500 on
 *      the real repo data. That failure is rendered in its own panel and does
 *      not take the view down — the alternative, catching it and showing an
 *      idle run, would report a healthy system that is actually broken.
 */
import { clock, Pill, StatusDot } from '@omega-harness/usecase-kit/ui';
import type { UseCaseViewProps } from '@omega-harness/usecase-kit';
import { Sparkline } from '../charts.js';
import type { TrainingMetrics } from '../client.js';
import { pct, pnlClass, regimeColor, signedUsd } from '../format.js';
import { useVictoriaLiveStream, useVictoriaMetrics, useVictoriaProgress } from '../hooks.js';
import { Async, Card, EmptyNote, ErrorNote, LoadingNote, Stat, ViewFrame } from './chrome.js';

/** A run is idle when nothing has cycled and the backend says so. */
function isIdle(m: TrainingMetrics): boolean {
  return m.status === 'idle' && m.current_cycle === 0 && m.total_trades === 0;
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

  const pnlSeries = (p.pnl_history ?? []).map((h) => h.pnl);
  const winSeries = (p.win_rate_history ?? []).map((h) => h.win_rate);
  const activity = (p.activity_log ?? []).slice(-24).reverse();
  const regime = p.current_regime?.name;

  return (
    <Card
      label="Run detail"
      right={
        regime != null && (
          <Pill color={regimeColor(regime)}>
            {regime}
            {p.current_regime?.confidence != null
              ? ` ${pct(p.current_regime.confidence, 0)}`
              : ''}
          </Pill>
        )
      }
    >
      <div className="flex flex-col gap-3.5">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <span className="font-mono text-[9.5px] uppercase tracking-[.08em] text-faint">
              PnL by cycle
            </span>
            <Sparkline values={pnlSeries} width={300} height={40} color="#4ec97a" label="PnL by cycle" />
          </div>
          <div className="flex flex-col gap-1.5">
            <span className="font-mono text-[9.5px] uppercase tracking-[.08em] text-faint">
              Win rate by cycle
            </span>
            <Sparkline values={winSeries} width={300} height={40} color="#5b9dff" label="win rate by cycle" />
          </div>
        </div>

        {activity.length === 0 ? (
          <EmptyNote title="No activity logged for this run" />
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

export function VictoriaLive(_props: UseCaseViewProps) {
  const metrics = useVictoriaMetrics();

  return (
    <ViewFrame
      title="Live"
      subtitle="A training run while it is running: the cycle counter off the event stream, aggregates off the database, and the run's own progress record."
    >
      <div className="flex flex-col gap-4">
        <Async state={metrics} what="loading training metrics">
          {(m) => (
            <div className="flex flex-col gap-4">
              <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
                <Stat
                  label="Cycle"
                  value={`${String(m.current_cycle)} / ${String(m.total_cycles)}`}
                  hint={m.status}
                />
                <Stat
                  label="Total PnL"
                  value={signedUsd(m.total_pnl)}
                  tone={pnlClass(m.total_pnl)}
                  hint={`realised ${signedUsd(m.realised_pnl)}`}
                />
                <Stat
                  label="Win rate"
                  value={pct(m.win_rate)}
                  hint={`${String(m.total_trades)} trades`}
                />
                <Stat
                  label="Memory"
                  value={String(m.memory_count.total)}
                  hint={`${String(m.memory_count.episodic)} episodic · ${String(m.memory_count.semantic)} semantic`}
                />
              </div>

              {isIdle(m) && (
                <Card>
                  <EmptyNote
                    title="No training run in flight"
                    detail="The omega API reports status “idle” with no cycles and no trades. Start one with scripts/run_training.py and this view fills in live; completed runs are in the Runs tab."
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
          )}
        </Async>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <StreamPanel />
          <ProgressPanel />
        </div>
      </div>
    </ViewFrame>
  );
}
