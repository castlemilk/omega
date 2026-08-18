/**
 * Victoria's charts.
 *
 * Bespoke SVG, matching the idiom `PulseSparkline` established: thin strokes,
 * palette tokens, mono numerals, no library. All the arithmetic lives in
 * `./geometry.ts` so it can be asserted to exact coordinates; this file is the
 * markup around it.
 */
import {
  areaPath,
  correlationColor,
  extent,
  linePath,
  scaleX,
  scaleY,
  ticks,
  trainEndX,
  type Box,
} from './geometry.js';

const AXIS = '#3d3d45'; // ghost
const GRID = 'rgba(255,255,255,.05)';

/** A compact inline trend line, sized for a stat tile. */
export function Sparkline({
  values,
  width = 120,
  height = 28,
  color = '#4ec97a',
  label,
}: {
  values: readonly number[];
  width?: number;
  height?: number;
  color?: string;
  label?: string;
}) {
  if (values.length < 2) {
    return (
      <div
        className="flex items-center font-mono text-[9.5px] text-faint"
        style={{ width, height }}
      >
        no history
      </div>
    );
  }
  const box: Box = { width, height, padLeft: 1, padRight: 1, padTop: 3, padBottom: 3 };
  const ext = extent(values);
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${String(width)} ${String(height)}`}
      role="img"
      aria-label={label ?? 'trend'}
      className="flex-none overflow-visible"
    >
      <path d={areaPath(values, ext, box)} fill={color} opacity={0.12} />
      <path
        d={linePath(values, ext, box)}
        fill="none"
        stroke={color}
        strokeWidth={1.25}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

export interface LineSeries {
  values: readonly number[];
  color: string;
  label: string;
  /** Dashed series read as secondary — the benchmark, not the strategy. */
  dashed?: boolean;
  fill?: boolean;
}

/**
 * The full-size line chart: axis ticks, gridlines, several series on one scale,
 * and the IS/OOS divider.
 *
 * All series share one extent deliberately. Two equity curves on independent
 * axes can be drawn to look identical while one made money and the other lost
 * it, and comparing the strategy against its benchmark is the entire reason the
 * benchmark is on the chart.
 */
export function LineChart({
  series,
  height = 260,
  width = 720,
  trainEnd,
  xLabels,
  formatY = (v: number) => v.toFixed(0),
  tickCount = 4,
}: {
  series: readonly LineSeries[];
  height?: number;
  width?: number;
  /** Index into the series where in-sample ends. Absent or out of range: no marker. */
  trainEnd?: number | null;
  /** Optional labels for the x axis; first and last are drawn. */
  xLabels?: readonly string[];
  formatY?: (value: number) => string;
  tickCount?: number;
}) {
  const box: Box = { width, height, padLeft: 52, padRight: 12, padTop: 12, padBottom: 24 };
  const all = series.flatMap((s) => [...s.values]);
  const ext = extent(all);
  const count = Math.max(...series.map((s) => s.values.length), 0);
  const yTicks = ticks(ext, tickCount);
  const divider = trainEndX(trainEnd, count, box);
  const plotLeft = box.padLeft;
  const plotRight = width - box.padRight;
  const plotBottom = height - box.padBottom;

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${String(width)} ${String(height)}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={`${series.map((s) => s.label).join(' and ')} over ${String(count)} points`}
      className="block"
    >
      {/* horizontal gridlines + y labels */}
      {yTicks.map((t, i) => {
        const y = scaleY(t, ext, box);
        return (
          <g key={i}>
            <line x1={plotLeft} x2={plotRight} y1={y} y2={y} stroke={GRID} strokeWidth={1} />
            <text
              x={plotLeft - 7}
              y={y + 3}
              textAnchor="end"
              className="font-mono"
              fontSize={9}
              fill="#565660"
            >
              {formatY(t)}
            </text>
          </g>
        );
      })}

      <line x1={plotLeft} x2={plotLeft} y1={box.padTop} y2={plotBottom} stroke={AXIS} strokeWidth={1} />
      <line x1={plotLeft} x2={plotRight} y1={plotBottom} y2={plotBottom} stroke={AXIS} strokeWidth={1} />

      {/* the IS/OOS boundary: everything right of it is out of sample */}
      {divider !== null && (
        <g>
          <line
            x1={divider}
            x2={divider}
            y1={box.padTop}
            y2={plotBottom}
            stroke="#e8963c"
            strokeWidth={1}
            strokeDasharray="3 3"
          />
          <text
            x={divider + 4}
            y={box.padTop + 9}
            className="font-mono"
            fontSize={9}
            fill="#c99a5c"
          >
            OOS →
          </text>
        </g>
      )}

      {series.map((s, i) => (
        <g key={i}>
          {s.fill && <path d={areaPath(s.values, ext, box)} fill={s.color} opacity={0.1} />}
          <path
            d={linePath(s.values, ext, box)}
            fill="none"
            stroke={s.color}
            strokeWidth={1.4}
            strokeDasharray={s.dashed ? '4 3' : undefined}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        </g>
      ))}

      {xLabels && xLabels.length > 0 && (
        <>
          <text
            x={plotLeft}
            y={height - 7}
            className="font-mono"
            fontSize={9}
            fill="#565660"
          >
            {xLabels[0]}
          </text>
          <text
            x={plotRight}
            y={height - 7}
            textAnchor="end"
            className="font-mono"
            fontSize={9}
            fill="#565660"
          >
            {xLabels[xLabels.length - 1]}
          </text>
        </>
      )}

      {/* endpoint dot on the primary series, so "where are we now" is findable */}
      {series[0] && series[0].values.length > 0 && (
        <circle
          cx={scaleX(series[0].values.length - 1, series[0].values.length, box)}
          cy={scaleY(series[0].values[series[0].values.length - 1], ext, box)}
          r={2.5}
          fill={series[0].color}
        />
      )}
    </svg>
  );
}

/** Legend swatches, kept out of the SVG so they can wrap with the layout. */
export function ChartLegend({ series }: { series: readonly LineSeries[] }) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      {series.map((s) => (
        <span key={s.label} className="flex items-center gap-1.5 font-mono text-[9.5px] text-ink3">
          <span
            className="inline-block h-[2px] w-4 rounded-full"
            style={{ background: s.color, opacity: s.dashed ? 0.6 : 1 }}
          />
          {s.label}
        </span>
      ))}
    </div>
  );
}

/**
 * The correlation heat grid.
 *
 * A table of coloured cells, not a chart: the labels have to stay readable and
 * the diagonal has to be recognisable, and an SVG heatmap makes both harder for
 * no gain at this size.
 */
export function HeatGrid({
  labels,
  matrix,
}: {
  labels: readonly string[];
  matrix: readonly (readonly number[])[];
}) {
  return (
    <div className="overflow-x-auto">
      <table className="border-separate border-spacing-[2px] font-mono text-[9.5px]">
        <thead>
          <tr>
            <th className="p-0" />
            {labels.map((l) => (
              <th
                key={l}
                title={l}
                className="max-w-[54px] truncate p-1 text-left font-medium text-faint"
              >
                {l}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {labels.map((rowLabel, r) => (
            <tr key={rowLabel}>
              <th
                title={rowLabel}
                className="max-w-[110px] truncate p-1 text-right font-medium text-ink3"
              >
                {rowLabel}
              </th>
              {labels.map((colLabel, c) => {
                const v = matrix[r]?.[c];
                const known = typeof v === 'number' && Number.isFinite(v);
                return (
                  <td
                    key={colLabel}
                    title={`${rowLabel} × ${colLabel}: ${known ? v.toFixed(3) : 'n/a'}`}
                    className="h-6 min-w-[42px] rounded-[3px] text-center text-ink2"
                    style={{ background: known ? correlationColor(v) : 'transparent' }}
                  >
                    {known ? v.toFixed(2) : '—'}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
