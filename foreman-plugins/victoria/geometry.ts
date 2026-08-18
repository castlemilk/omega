/**
 * Chart maths, with no React and no SVG in sight.
 *
 * Foreman draws its own charts — `PulseSparkline` in `ui/primitives.tsx` is the
 * precedent and there is no chart library in the tree. Keeping the arithmetic
 * here rather than inline in the components is what makes it testable to exact
 * coordinates: a path string is a value, and a test that asserts the value
 * catches an inverted y-axis, which a test that asserts "it rendered a <path>"
 * never will.
 */

export interface Extent {
  min: number;
  max: number;
}

export interface Box {
  width: number;
  height: number;
  padLeft: number;
  padRight: number;
  padTop: number;
  padBottom: number;
}

/**
 * The closed interval a series spans.
 *
 * A flat series (every value identical) gets padded by ±1 rather than returning
 * a zero-width extent: dividing by that span produces Infinity, and the line
 * would vanish or blow past the viewport. Padding puts the flat line exactly
 * mid-plot, which is what it means.
 */
export function extent(values: readonly number[]): Extent {
  const finite = values.filter((v) => Number.isFinite(v));
  if (finite.length === 0) return { min: 0, max: 1 };
  let min = finite[0];
  let max = finite[0];
  for (const v of finite) {
    if (v < min) min = v;
    if (v > max) max = v;
  }
  if (min === max) return { min: min - 1, max: max + 1 };
  return { min, max };
}

/** Horizontal position of index `i` of `count` points, inclusive of both edges. */
export function scaleX(i: number, count: number, box: Box): number {
  const left = box.padLeft;
  const right = box.width - box.padRight;
  if (count <= 1) return left;
  return left + ((right - left) * i) / (count - 1);
}

/** Vertical position of `value`. SVG y grows downward, so the scale inverts. */
export function scaleY(value: number, ext: Extent, box: Box): number {
  const top = box.padTop;
  const bottom = box.height - box.padBottom;
  const span = ext.max - ext.min;
  if (span === 0) return (top + bottom) / 2;
  const clamped = Number.isFinite(value) ? value : ext.min;
  return bottom - ((clamped - ext.min) / span) * (bottom - top);
}

/** Round to 2dp so path strings are stable to assert and small to ship. */
function r2(n: number): number {
  return Math.round(n * 100) / 100;
}

/**
 * A polyline through `values` as an SVG path.
 *
 * Empty input yields an empty string rather than `"M"` — an invalid `d` makes
 * the browser drop the whole element, and a caller that renders nothing is
 * clearer than one that renders something broken.
 */
export function linePath(values: readonly number[], ext: Extent, box: Box): string {
  if (values.length === 0) return '';
  return values
    .map((v, i) => `${i === 0 ? 'M' : 'L'}${String(r2(scaleX(i, values.length, box)))} ${String(r2(scaleY(v, ext, box)))}`)
    .join(' ');
}

/**
 * The same polyline closed down to the baseline, for a filled area.
 *
 * The baseline is the plot's bottom edge, not y=0: when a series never crosses
 * zero, filling to zero would either escape the viewport or fill the entire
 * plot, and neither reads as "area under the curve".
 */
export function areaPath(values: readonly number[], ext: Extent, box: Box): string {
  if (values.length === 0) return '';
  const baseline = r2(box.height - box.padBottom);
  const first = r2(scaleX(0, values.length, box));
  const last = r2(scaleX(values.length - 1, values.length, box));
  return `${linePath(values, ext, box)} L${String(last)} ${String(baseline)} L${String(first)} ${String(baseline)} Z`;
}

/**
 * Where the in-sample/out-of-sample divider sits, or null when there isn't one.
 *
 * `trainEnd` is an index into the point array. Guarding it matters: the backend
 * omits the field when it is zero (Connect drops zero-valued fields), and an
 * unguarded 0 would draw a "train ends here" rule hard against the left axis,
 * asserting the entire curve is out-of-sample. Out-of-range values are refused
 * for the same reason — a marker at the wrong place is worse than none.
 */
export function trainEndX(
  trainEnd: number | undefined | null,
  count: number,
  box: Box,
): number | null {
  if (trainEnd == null || !Number.isFinite(trainEnd)) return null;
  if (trainEnd <= 0 || trainEnd >= count) return null;
  return scaleX(trainEnd, count, box);
}

/**
 * Evenly-spaced axis ticks across an extent, endpoints included.
 *
 * `count` is the number of intervals, so `ticks(ext, 4)` yields five labels.
 */
export function ticks(ext: Extent, count: number): number[] {
  if (count < 1) return [ext.min, ext.max];
  const step = (ext.max - ext.min) / count;
  return Array.from({ length: count + 1 }, (_, i) => ext.min + step * i);
}

// ── Funnel ───────────────────────────────────────────────────────────────────

export interface FunnelStep {
  label: string;
  count: number;
  /** Why the drop from the previous step happened. First step has none. */
  note?: string;
}

export interface FunnelBar extends FunnelStep {
  x: number;
  y: number;
  width: number;
  height: number;
  /** Share of the first step, 0..1. The first bar is always 1. */
  share: number;
  /** How many were lost between the previous step and this one. */
  dropped: number;
}

/**
 * A stepped funnel: bars whose widths are shares of the FIRST step.
 *
 * Widths are relative to the top of the funnel, not to the previous bar,
 * because the question a funnel answers is "what fraction of everything
 * survived to here" — normalising each bar against its predecessor makes a
 * 90% → 90% → 90% funnel look like three identical bars and hides that only
 * 73% got through.
 *
 * A first step of zero yields zero-width bars rather than NaN: nothing was
 * evaluated, so nothing survived, and an empty funnel is the truthful drawing.
 * Later steps are NOT clamped to the first — if a downstream count somehow
 * exceeds the top, the bar overflows and the operator sees the contradiction
 * instead of a silently truncated one.
 */
export function funnelBars(steps: readonly FunnelStep[], box: Box, barHeight = 26, gap = 10): FunnelBar[] {
  const span = box.width - box.padLeft - box.padRight;
  const top = steps.length > 0 ? steps[0].count : 0;
  return steps.map((step, i) => {
    const share = top > 0 ? step.count / top : 0;
    return {
      ...step,
      x: box.padLeft,
      y: box.padTop + i * (barHeight + gap),
      width: span * share,
      height: barHeight,
      share,
      dropped: i === 0 ? 0 : steps[i - 1].count - step.count,
    };
  });
}

/** The height a funnel of `n` steps needs, so the SVG viewBox fits its content. */
export function funnelHeight(n: number, box: Box, barHeight = 26, gap = 10): number {
  if (n <= 0) return box.padTop + box.padBottom;
  return box.padTop + n * barHeight + (n - 1) * gap + box.padBottom;
}

// ── Grouped bars ─────────────────────────────────────────────────────────────

export interface BarRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * Side-by-side bars: `groups[g][s]` is series `s`'s value in group `g`.
 *
 * Every series shares one scale, for the same reason `LineChart` puts every
 * line on one extent — two conviction histograms drawn to independent maxima
 * can be made to look identical while one traded twice as often. The scale
 * starts at zero rather than at the minimum: these are counts and shares, and a
 * bar chart with a non-zero floor exaggerates every difference on it.
 *
 * Negative values are clamped to zero height rather than drawn below the axis;
 * nothing this draws (counts, percentages) can legitimately be negative, so a
 * negative is bad data and must not silently invert a bar.
 */
export function groupedBars(
  groups: readonly (readonly number[])[],
  box: Box,
  groupGap = 14,
  barGap = 3,
): BarRect[][] {
  const span = box.width - box.padLeft - box.padRight;
  const baseline = box.height - box.padBottom;
  const plotHeight = baseline - box.padTop;
  const seriesCount = groups.reduce((n, g) => Math.max(n, g.length), 0);
  if (groups.length === 0 || seriesCount === 0 || span <= 0) return groups.map(() => []);

  let max = 0;
  for (const g of groups) for (const v of g) if (Number.isFinite(v) && v > max) max = v;

  const groupWidth = (span - groupGap * (groups.length - 1)) / groups.length;
  const barWidth = (groupWidth - barGap * (seriesCount - 1)) / seriesCount;

  return groups.map((group, gi) => {
    const groupX = box.padLeft + gi * (groupWidth + groupGap);
    return group.map((value, si) => {
      const v = Number.isFinite(value) && value > 0 ? value : 0;
      const height = max > 0 ? (v / max) * plotHeight : 0;
      return {
        x: groupX + si * (barWidth + barGap),
        y: baseline - height,
        width: barWidth,
        height,
      };
    });
  });
}

/**
 * Which of nine correlation buckets a value falls in, -4..4.
 *
 * Bucketed rather than continuously interpolated so that a wall of cells reads
 * as a small number of distinct bands — the point of a correlation grid is
 * spotting clusters, and a smooth ramp hides the boundary between "0.3, fine"
 * and "0.7, these two signals are the same signal". Bounds are inclusive-low so
 * exactly 0.25 lands in the first positive band, and values are clamped rather
 * than dropped because a correlation matrix with a 1.0000000002 on the diagonal
 * is a floating-point artefact, not bad data.
 */
export function correlationBucket(value: number): number {
  if (!Number.isFinite(value)) return 0;
  const v = Math.max(-1, Math.min(1, value));
  const sign = v < 0 ? -1 : 1;
  const mag = Math.abs(v);
  if (mag < 0.25) return 0;
  if (mag < 0.5) return sign * 1;
  if (mag < 0.75) return sign * 2;
  if (mag < 1) return sign * 3;
  return sign * 4;
}

/** Bucket -4..4 to a fill. Positive warms toward the accent, negative cools to info. */
export function correlationColor(value: number): string {
  const bucket = correlationBucket(value);
  const alpha = [0.06, 0.18, 0.34, 0.52, 0.72][Math.abs(bucket)];
  // Foreman's `info` for negative, `accent` for positive — the same two colours
  // the chrome already uses for "cool/informational" and "hot/attention".
  const rgb = bucket < 0 ? '91,157,255' : '232,150,60';
  return `rgba(${rgb},${String(alpha)})`;
}
