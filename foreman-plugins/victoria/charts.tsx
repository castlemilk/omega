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
  funnelBars,
  funnelHeight,
  groupedBars,
  linePath,
  regimeBands,
  scaleX,
  scaleY,
  ticks,
  trainEndX,
  type Box,
  type FunnelStep,
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
export interface ChartMarker {
  /** Index into the primary series' x positions. */
  index: number;
  /** The y value, on the shared extent. */
  value: number;
  color: string;
  /** Tooltip text — the marker's reason for existing. */
  label?: string;
}

export function LineChart({
  series,
  height = 260,
  width = 720,
  trainEnd,
  xLabels,
  formatY = (v: number) => v.toFixed(0),
  tickCount = 4,
  markers,
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
  /** Point events (e.g. executed trades) drawn on the shared scale. */
  markers?: readonly ChartMarker[];
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

      {/* point events on the shared scale — a marker off-scale is refused by
          the same logic as trainEndX: wrong place is worse than absent */}
      {markers?.map((m, i) =>
        Number.isFinite(m.value) && m.index >= 0 && m.index < count ? (
          <circle
            key={i}
            cx={scaleX(m.index, count, box)}
            cy={scaleY(m.value, ext, box)}
            r={2.75}
            fill={m.color}
            stroke="#0d0d10"
            strokeWidth={0.75}
          >
            {m.label != null && <title>{m.label}</title>}
          </circle>
        ) : null,
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
 * The stepped funnel.
 *
 * Bars, not a tapering polygon: a polygon funnel encodes the count in an area
 * the eye reads as a length anyway, and it cannot show a step that grew. Widths
 * are shares of the first step (see `funnelBars`), each bar carries its own
 * count and share as text, and the drop between steps is stated in words
 * underneath — the drop is the finding, and leaving it to be inferred from two
 * bar lengths is how a funnel becomes decoration.
 */
export function Funnel({
  steps,
  width = 720,
  color = 'var(--uc-accent)',
}: {
  steps: readonly FunnelStep[];
  width?: number;
  color?: string;
}) {
  const barHeight = 30;
  // The gap carries each step's drop note, and `padBottom` is what keeps the
  // LAST step's note inside the viewBox — without it the final drop ("24
  // filtered") is drawn below the SVG and silently clipped, which was exactly
  // the bug the first live walk of this view found.
  const gap = 34;
  const box: Box = { width, height: 0, padLeft: 0, padRight: 0, padTop: 0, padBottom: 20 };
  const bars = funnelBars(steps, box, barHeight, gap);
  const height = funnelHeight(steps.length, box, barHeight, gap);

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${String(width)} ${String(height)}`}
      role="img"
      aria-label={`funnel: ${steps.map((s) => `${s.label} ${String(s.count)}`).join(', ')}`}
      className="block"
    >
      {bars.map((bar) => (
        <g key={bar.label}>
          {/* The track: the full width the first step occupied, so a short bar
              reads as a share rather than as a bar of unknown scale. */}
          <rect x={bar.x} y={bar.y} width={width} height={bar.height} rx={3} fill="rgba(255,255,255,.04)" />
          <rect x={bar.x} y={bar.y} width={bar.width} height={bar.height} rx={3} fill={color} opacity={0.28} />
          <rect x={bar.x} y={bar.y} width={Math.min(bar.width, 2)} height={bar.height} fill={color} />
          <text x={bar.x + 10} y={bar.y + 19} className="font-mono" fontSize={11} fill="#e8e8ea">
            {bar.label}
          </text>
          <text
            x={width - 10}
            y={bar.y + 19}
            textAnchor="end"
            className="font-mono"
            fontSize={11}
            fill="#c8c8ce"
          >
            {String(bar.count)} · {(bar.share * 100).toFixed(1)}%
          </text>
          {bar.note != null && (
            <text x={bar.x + 10} y={bar.y + bar.height + 14} className="font-mono" fontSize={9.5} fill="#8a8a92">
              ↳ {bar.note}
            </text>
          )}
        </g>
      ))}
    </svg>
  );
}

/**
 * Side-by-side bars for A-vs-B comparisons.
 *
 * Two runs' histograms on one scale (see `groupedBars`), each group labelled
 * under the axis and each bar carrying its value above it. Values are formatted
 * by the caller, because the same chart draws counts in one panel and
 * percentages in the next and only the caller knows which.
 */
export function GroupedBarChart({
  groups,
  seriesColors,
  seriesLabels,
  formatValue = (v: number) => v.toFixed(2),
  width = 340,
  height = 170,
}: {
  groups: readonly { label: string; values: readonly number[] }[];
  seriesColors: readonly string[];
  seriesLabels: readonly string[];
  formatValue?: (value: number) => string;
  width?: number;
  height?: number;
}) {
  const box: Box = { width, height, padLeft: 6, padRight: 6, padTop: 18, padBottom: 26 };
  const rects = groupedBars(groups.map((g) => g.values), box);
  const baseline = height - box.padBottom;

  return (
    <div className="flex flex-col gap-2">
      <svg
        width="100%"
        viewBox={`0 0 ${String(width)} ${String(height)}`}
        role="img"
        aria-label={`${seriesLabels.join(' versus ')} across ${groups.map((g) => g.label).join(', ')}`}
        className="block"
      >
        <line x1={box.padLeft} x2={width - box.padRight} y1={baseline} y2={baseline} stroke={AXIS} strokeWidth={1} />
        {rects.map((group, gi) => (
          <g key={groups[gi].label}>
            {group.map((rect, si) => (
              <g key={si}>
                <rect
                  x={rect.x}
                  y={rect.y}
                  width={rect.width}
                  height={rect.height}
                  fill={seriesColors[si] ?? '#6b6b74'}
                  opacity={0.75}
                  rx={2}
                />
                <text
                  x={rect.x + rect.width / 2}
                  y={rect.y - 4}
                  textAnchor="middle"
                  className="font-mono"
                  fontSize={8.5}
                  fill="#8a8a92"
                >
                  {formatValue(groups[gi].values[si])}
                </text>
              </g>
            ))}
            <text
              x={(group[0]?.x ?? box.padLeft) + (group.length * (group[0]?.width ?? 0)) / 2}
              y={baseline + 13}
              textAnchor="middle"
              className="font-mono"
              fontSize={9}
              fill="#565660"
            >
              {groups[gi].label}
            </text>
          </g>
        ))}
      </svg>
      <div className="flex flex-wrap items-center gap-3">
        {seriesLabels.map((label, i) => (
          <span key={label} className="flex items-center gap-1.5 font-mono text-[9.5px] text-ink3">
            <span
              className="inline-block h-2 w-2 rounded-[2px]"
              style={{ background: seriesColors[i] ?? '#6b6b74' }}
            />
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}

/**
 * The regime timeline: consecutive same-regime cycles as horizontal bands.
 *
 * Padding defaults match `LineChart`'s plot area so a strip rendered directly
 * beneath one shares its x scale — a crisis band must sit under the stretch of
 * curve it actually labelled. Colours come from the caller (`regimeColor` in
 * format.ts — domain colours have one home); a null-regime band renders as a
 * hollow hatch, because "no regime recorded" is a gap, not a fourth regime.
 */
export function RegimeStrip({
  regimes,
  width = 720,
  height = 16,
  padLeft = 52,
  padRight = 12,
  colorOf,
}: {
  regimes: readonly (string | null | undefined)[];
  width?: number;
  height?: number;
  padLeft?: number;
  padRight?: number;
  colorOf: (regime: string | null) => string;
}) {
  const box: Box = { width, height, padLeft, padRight, padTop: 0, padBottom: 0 };
  const bands = regimeBands(regimes, box);
  if (bands.length === 0) return null;
  return (
    <svg
      width="100%"
      viewBox={`0 0 ${String(width)} ${String(height)}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={`regime timeline over ${String(regimes.length)} cycles`}
      className="block"
    >
      {bands.map((band) => (
        <rect
          key={band.start}
          x={band.x}
          y={2}
          width={band.width}
          height={height - 4}
          rx={2}
          fill={band.regime === null ? 'rgba(255,255,255,.04)' : colorOf(band.regime)}
          opacity={band.regime === null ? 1 : 0.55}
        >
          <title>
            {`${band.regime ?? 'no regime recorded'} · cycles ${String(band.start)}–${String(band.end)} (${String(band.count)})`}
          </title>
        </rect>
      ))}
    </svg>
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
