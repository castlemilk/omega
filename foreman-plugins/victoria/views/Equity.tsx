/**
 * Equity — the curve, at full size.
 *
 * The strategy against its benchmark on one shared scale, with the in-sample /
 * out-of-sample divider drawn where `GetEquityCurve` reports it. That marker is
 * the point of the view: an equity curve that looks wonderful up to `train_end`
 * and flat after it is an overfit, and you cannot see that without the line.
 *
 * `trainEnd` is guarded in `geometry.trainEndX` rather than here, because the
 * guard is a numeric fact worth a unit test: Connect omits zero-valued fields,
 * so "no boundary" and "boundary at index 0" arrive identically, and drawing
 * the marker at 0 would claim the entire curve is out of sample.
 */
import { useMemo } from 'react';
import { Pill } from '@omega-harness/usecase-kit/ui';
import type { UseCaseViewProps } from '@omega-harness/usecase-kit';
import { ChartLegend, LineChart, type LineSeries } from '../charts.js';
import { pct, ratio, usd } from '../format.js';
import { useVictoriaEquity } from '../hooks.js';
import { Async, Card, EmptyNote, Stat, ViewFrame } from './chrome.js';

/** Peak-to-trough, as a fraction. Used only when the API sends no `dd` series. */
export function maxDrawdown(values: readonly number[]): number {
  let peak = -Infinity;
  let worst = 0;
  for (const v of values) {
    if (!Number.isFinite(v)) continue;
    if (v > peak) peak = v;
    if (peak > 0) {
      const dd = (v - peak) / peak;
      if (dd < worst) worst = dd;
    }
  }
  return worst;
}

export function VictoriaEquity(_props: UseCaseViewProps) {
  const state = useVictoriaEquity();

  return (
    <ViewFrame
      title="Equity"
      subtitle="Cumulative equity against the BTC benchmark. The dashed rule marks where in-sample training ends and out-of-sample begins."
    >
      <Async state={state} what="loading equity curve">
        {(curve) => {
          const points = curve.points ?? [];
          if (points.length < 2) {
            return (
              <Card>
                <EmptyNote
                  title="No equity curve"
                  detail="GetEquityCurve returned no points. The curve is written during backtests and paper runs; an unseeded database has none."
                />
              </Card>
            );
          }
          return <EquityBody points={points} trainEnd={curve.trainEnd} />;
        }}
      </Async>
    </ViewFrame>
  );
}

function EquityBody({
  points,
  trainEnd,
}: {
  points: { date?: string; omega?: number; btc?: number; dd?: number }[];
  trainEnd?: number;
}) {
  const omega = useMemo(() => points.map((p) => p.omega ?? 0), [points]);
  const btc = useMemo(() => points.map((p) => p.btc ?? 0), [points]);
  const dd = useMemo(() => points.map((p) => p.dd ?? 0), [points]);
  const dates = useMemo(() => points.map((p) => p.date ?? ''), [points]);

  const hasBtc = btc.some((v) => v !== 0);
  const hasDd = dd.some((v) => v !== 0);

  const series: LineSeries[] = [
    { values: omega, color: 'var(--uc-accent)', label: 'Victoria', fill: true },
    ...(hasBtc ? [{ values: btc, color: '#5b9dff', label: 'BTC benchmark', dashed: true }] : []),
  ];

  const first = omega[0];
  const last = omega[omega.length - 1];
  const totalReturn = first !== 0 ? (last - first) / Math.abs(first) : null;
  const drawdown = hasDd ? Math.min(...dd) : maxDrawdown(omega);
  const oosShare =
    trainEnd != null && trainEnd > 0 && trainEnd < points.length
      ? 1 - trainEnd / points.length
      : null;

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
        <Stat label="Final equity" value={usd(last)} hint={`from ${usd(first)}`} />
        <Stat
          label="Total return"
          value={totalReturn === null ? '—' : pct(totalReturn)}
          tone={totalReturn !== null && totalReturn < 0 ? 'text-danger' : 'text-ok'}
        />
        <Stat label="Max drawdown" value={pct(drawdown)} tone="text-danger" hint={hasDd ? 'reported' : 'derived'} />
        <Stat
          label="Out of sample"
          value={oosShare === null ? '—' : pct(oosShare, 0)}
          hint={trainEnd != null && trainEnd > 0 ? `train ends at ${String(trainEnd)}` : 'no boundary reported'}
        />
      </div>

      <Card
        label="Equity curve"
        right={
          <div className="flex items-center gap-3">
            <ChartLegend series={series} />
            <span className="font-mono text-[9.5px] text-faint">
              {String(points.length)} points
            </span>
          </div>
        }
      >
        <LineChart
          series={series}
          trainEnd={trainEnd}
          height={300}
          xLabels={dates}
          formatY={(v) => usd(v).replace('.00', '')}
        />
      </Card>

      {hasDd && (
        <Card label="Drawdown">
          <LineChart
            series={[{ values: dd, color: '#e5675b', label: 'Drawdown', fill: true }]}
            trainEnd={trainEnd}
            height={140}
            tickCount={2}
            xLabels={dates}
            formatY={(v) => pct(v, 0)}
          />
        </Card>
      )}

      {trainEnd != null && trainEnd > 0 && (
        <div className="flex items-center gap-2">
          <Pill color="#e8963c">train_end {String(trainEnd)}</Pill>
          <span className="text-[10.5px] text-muted">
            Everything right of the dashed rule is out of sample —{' '}
            {ratio(points.length - trainEnd, 0)} of {String(points.length)} points the model
            never saw during fitting.
          </span>
        </div>
      )}
    </div>
  );
}
