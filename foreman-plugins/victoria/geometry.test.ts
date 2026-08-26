/**
 * Chart maths, asserted as values.
 *
 * The house rule: a test that asserts a path string was produced catches
 * nothing. These assert the coordinates, so an inverted y-axis, an off-by-one
 * on the last point, or a train_end marker drawn against the left axis all fail
 * loudly.
 */
import { describe, expect, it } from 'vitest';
import {
  areaPath,
  correlationBucket,
  correlationColor,
  drawdownSeries,
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
} from './geometry.js';

/** A box with round numbers, so every expected coordinate below is exact. */
const box: Box = { width: 120, height: 100, padLeft: 20, padRight: 20, padTop: 10, padBottom: 10 };
// plot area: x from 20 to 100 (80 wide), y from 10 to 90 (80 tall)

describe('extent', () => {
  it('returns the closed interval a series spans', () => {
    expect(extent([3, 1, 4, 1, 5])).toEqual({ min: 1, max: 5 });
    expect(extent([-8, -2])).toEqual({ min: -8, max: -2 });
  });

  it('pads a flat series so the line lands mid-plot instead of dividing by zero', () => {
    expect(extent([7, 7, 7])).toEqual({ min: 6, max: 8 });
    expect(scaleY(7, extent([7, 7, 7]), box)).toBe(50); // exactly halfway
  });

  it('ignores non-finite values, and falls back to 0..1 when nothing is finite', () => {
    expect(extent([1, NaN, 9, Infinity])).toEqual({ min: 1, max: 9 });
    expect(extent([])).toEqual({ min: 0, max: 1 });
    expect(extent([NaN, Infinity])).toEqual({ min: 0, max: 1 });
  });
});

describe('scaleX', () => {
  it('places the first point on the left edge and the last on the right', () => {
    expect(scaleX(0, 5, box)).toBe(20);
    expect(scaleX(4, 5, box)).toBe(100);
  });

  it('spaces intermediate points evenly', () => {
    expect(scaleX(1, 5, box)).toBe(40);
    expect(scaleX(2, 5, box)).toBe(60);
    expect(scaleX(3, 5, box)).toBe(80);
  });

  it('pins a single point to the left edge rather than dividing by zero', () => {
    expect(scaleX(0, 1, box)).toBe(20);
    expect(scaleX(0, 0, box)).toBe(20);
  });
});

describe('scaleY', () => {
  const ext = { min: 0, max: 100 };

  it('inverts, because SVG y grows downward', () => {
    expect(scaleY(100, ext, box)).toBe(10); // max at the top
    expect(scaleY(0, ext, box)).toBe(90); // min at the bottom
    expect(scaleY(50, ext, box)).toBe(50);
  });

  it('scales a negative extent the same way', () => {
    expect(scaleY(-10, { min: -10, max: 10 }, box)).toBe(90);
    expect(scaleY(10, { min: -10, max: 10 }, box)).toBe(10);
    expect(scaleY(0, { min: -10, max: 10 }, box)).toBe(50);
  });

  it('puts a zero-span extent mid-plot and treats non-finite as the floor', () => {
    expect(scaleY(5, { min: 5, max: 5 }, box)).toBe(50);
    expect(scaleY(NaN, ext, box)).toBe(90);
  });
});

describe('linePath', () => {
  it('produces the exact path for a known series', () => {
    // 3 points across x 20..100 → 20, 60, 100; values 0/50/100 over 0..100 → y 90/50/10
    expect(linePath([0, 50, 100], { min: 0, max: 100 }, box)).toBe('M20 90 L60 50 L100 10');
  });

  it('rounds to 2dp so paths are stable and small', () => {
    // 3 points, values 0/1/3 over 0..3 → y 90, 90-(1/3)*80=63.33, 10
    expect(linePath([0, 1, 3], { min: 0, max: 3 }, box)).toBe('M20 90 L60 63.33 L100 10');
  });

  it('renders nothing for an empty series rather than an invalid `d`', () => {
    expect(linePath([], { min: 0, max: 1 }, box)).toBe('');
    expect(areaPath([], { min: 0, max: 1 }, box)).toBe('');
  });

  it('draws a single point as a lone move', () => {
    expect(linePath([5], { min: 0, max: 10 }, box)).toBe('M20 50');
  });
});

describe('areaPath', () => {
  it('closes the line down to the plot floor, not to y=0', () => {
    // The series never reaches the extent's min, so the fill must still reach
    // the bottom of the plot (y=90) — filling to the value's own y would leave
    // a floating ribbon.
    expect(areaPath([50, 100], { min: 0, max: 100 }, box)).toBe(
      'M20 50 L100 10 L100 90 L20 90 Z',
    );
  });
});

describe('trainEndX', () => {
  it('places the divider at the boundary index', () => {
    // index 2 of 5 points → same x as scaleX(2, 5)
    expect(trainEndX(2, 5, box)).toBe(60);
  });

  it('refuses zero, because Connect omits a zero train_end from the JSON', () => {
    // A marker at index 0 would sit on the y-axis and claim the whole curve is
    // out of sample — strictly worse than drawing no marker.
    expect(trainEndX(0, 5, box)).toBeNull();
    expect(trainEndX(undefined, 5, box)).toBeNull();
    expect(trainEndX(null, 5, box)).toBeNull();
  });

  it('refuses an index at or past the end, and non-finite values', () => {
    expect(trainEndX(5, 5, box)).toBeNull();
    expect(trainEndX(9, 5, box)).toBeNull();
    expect(trainEndX(-3, 5, box)).toBeNull();
    expect(trainEndX(NaN, 5, box)).toBeNull();
  });
});

describe('ticks', () => {
  it('returns count+1 evenly spaced values, endpoints included', () => {
    expect(ticks({ min: 0, max: 100 }, 4)).toEqual([0, 25, 50, 75, 100]);
    expect(ticks({ min: -1, max: 1 }, 2)).toEqual([-1, 0, 1]);
  });

  it('degrades to the endpoints for a nonsense count', () => {
    expect(ticks({ min: 2, max: 8 }, 0)).toEqual([2, 8]);
  });
});

describe('correlationBucket', () => {
  it('buckets magnitude into four bands per sign, plus a neutral zero', () => {
    expect(correlationBucket(0)).toBe(0);
    expect(correlationBucket(0.24)).toBe(0);
    expect(correlationBucket(0.25)).toBe(1); // inclusive lower bound
    expect(correlationBucket(0.49)).toBe(1);
    expect(correlationBucket(0.5)).toBe(2);
    expect(correlationBucket(0.74)).toBe(2);
    expect(correlationBucket(0.75)).toBe(3);
    expect(correlationBucket(0.99)).toBe(3);
    expect(correlationBucket(1)).toBe(4);
  });

  it('mirrors the bands for negative correlations', () => {
    expect(correlationBucket(-0.24)).toBe(0);
    expect(correlationBucket(-0.25)).toBe(-1);
    expect(correlationBucket(-0.6)).toBe(-2);
    expect(correlationBucket(-0.8)).toBe(-3);
    expect(correlationBucket(-1)).toBe(-4);
  });

  it('clamps floating-point overshoot on the diagonal instead of dropping it', () => {
    expect(correlationBucket(1.0000000002)).toBe(4);
    expect(correlationBucket(-1.0000000002)).toBe(-4);
    expect(correlationBucket(NaN)).toBe(0);
  });
});

describe('correlationColor', () => {
  it('warms toward the accent for positive and cools to info for negative', () => {
    expect(correlationColor(1)).toBe('rgba(232,150,60,0.72)');
    expect(correlationColor(0.6)).toBe('rgba(232,150,60,0.34)');
    expect(correlationColor(-1)).toBe('rgba(91,157,255,0.72)');
    expect(correlationColor(-0.3)).toBe('rgba(91,157,255,0.18)');
  });

  it('renders an uncorrelated pair as barely-there accent rather than nothing', () => {
    // bucket 0 has no sign, so it takes the positive rgb at the lowest alpha.
    expect(correlationColor(0)).toBe('rgba(232,150,60,0.06)');
  });
});

// ── Phase-2 geometry ─────────────────────────────────────────────────────────

/** A funnel box with round numbers: 100 units of usable width. */
const funnelBox: Box = { width: 100, height: 0, padLeft: 0, padRight: 0, padTop: 0, padBottom: 0 };

describe('funnelBars', () => {
  // The real shape of one run: bt_v132a_crisis evaluates 770 ticker-cycles,
  // proposes on 170 of them, and trades 146.
  const steps = [
    { label: 'Evaluated', count: 770 },
    { label: 'Proposed', count: 170 },
    { label: 'Traded', count: 146 },
  ];

  it('scales every bar against the FIRST step, not against its predecessor', () => {
    // The mistake this catches: normalising each bar against the one above it
    // draws 770 → 170 → 146 as "full, 22%, 86%", which reads as a funnel that
    // barely loses anything at the last step. It loses 81% overall.
    const bars = funnelBars(steps, funnelBox, 20, 10);
    expect(bars.map((b) => b.width)).toEqual([100, (170 / 770) * 100, (146 / 770) * 100]);
    expect(bars[1].share).toBeCloseTo(170 / 770, 12);
    expect(bars[2].share).toBeCloseTo(146 / 770, 12);
  });

  it('reports the drop into each step, and none for the first', () => {
    const bars = funnelBars(steps, funnelBox, 20, 10);
    expect(bars.map((b) => b.dropped)).toEqual([0, 600, 24]);
  });

  it('stacks bars by height plus gap, from the top pad', () => {
    const bars = funnelBars(steps, funnelBox, 20, 10);
    expect(bars.map((b) => b.y)).toEqual([0, 30, 60]);
    expect(bars.every((b) => b.x === 0 && b.height === 20)).toBe(true);
    expect(funnelHeight(3, funnelBox, 20, 10)).toBe(80);
    expect(funnelHeight(0, funnelBox, 20, 10)).toBe(0);
  });

  it('draws an empty funnel rather than NaN when nothing was evaluated', () => {
    const bars = funnelBars(
      [
        { label: 'Evaluated', count: 0 },
        { label: 'Traded', count: 0 },
      ],
      funnelBox,
    );
    expect(bars.map((b) => b.width)).toEqual([0, 0]);
    expect(bars.map((b) => b.share)).toEqual([0, 0]);
  });

  it('lets a later step overflow rather than clamping a contradiction out of sight', () => {
    // A step bigger than the top is bad data. Silently truncating it to 100%
    // would hide the only evidence that something is wrong.
    const bars = funnelBars(
      [
        { label: 'a', count: 10 },
        { label: 'b', count: 20 },
      ],
      funnelBox,
    );
    expect(bars[1].width).toBe(200);
    expect(bars[1].dropped).toBe(-10);
  });

  it('is empty for no steps', () => {
    expect(funnelBars([], funnelBox)).toEqual([]);
  });
});

describe('groupedBars', () => {
  /** 100 wide, 100 tall usable; padTop 0 and padBottom 0 keep the arithmetic exact. */
  const barBox: Box = { width: 100, height: 100, padLeft: 0, padRight: 0, padTop: 0, padBottom: 0 };

  it('puts every series on one scale, zero-based', () => {
    // Two groups, two series. groupWidth = (100 - 14) / 2 = 43;
    // barWidth = (43 - 3) / 2 = 20.
    const rects = groupedBars([[59, 68], [1, 1]], barBox);
    expect(rects[0][0]).toEqual({ x: 0, y: 100 - (59 / 68) * 100, width: 20, height: (59 / 68) * 100 });
    expect(rects[0][1]).toEqual({ x: 23, y: 0, width: 20, height: 100 });
    // The second group is scaled against the SAME maximum, which is the point:
    // a trade band of 1 next to a hold band of 68 must look like almost nothing.
    expect(rects[1][0].height).toBeCloseTo((1 / 68) * 100, 10);
    expect(rects[1][0].x).toBe(57);
  });

  it('sits every bar on the baseline', () => {
    const rects = groupedBars([[10, 5]], barBox);
    for (const rect of rects[0]) expect(rect.y + rect.height).toBeCloseTo(100, 10);
  });

  it('draws zero-height bars when every value is zero, rather than dividing by it', () => {
    const rects = groupedBars([[0, 0]], barBox);
    expect(rects[0].map((r) => r.height)).toEqual([0, 0]);
    expect(rects[0].every((r) => r.y === 100)).toBe(true);
  });

  it('clamps a negative to zero height instead of inverting the bar', () => {
    const rects = groupedBars([[-4, 8]], barBox);
    expect(rects[0][0].height).toBe(0);
    expect(rects[0][1].height).toBe(100);
  });

  it('is empty for no groups', () => {
    expect(groupedBars([], barBox)).toEqual([]);
    expect(groupedBars([[]], barBox)).toEqual([[]]);
  });
});

describe('regimeBands', () => {
  // plot area is x 20..100 (80 wide); 8 cycles → each slot is exactly 10 wide

  it('compresses consecutive runs into bands with exact slot-edge positions', () => {
    const bands = regimeBands(
      ['normal', 'normal', 'normal', 'crisis', 'crisis', 'high_vol', 'normal', 'normal'],
      box,
    );
    expect(bands).toEqual([
      { regime: 'normal', start: 0, end: 2, count: 3, x: 20, width: 30 },
      { regime: 'crisis', start: 3, end: 4, count: 2, x: 50, width: 20 },
      { regime: 'high_vol', start: 5, end: 5, count: 1, x: 70, width: 10 },
      { regime: 'normal', start: 6, end: 7, count: 2, x: 80, width: 20 },
    ]);
  });

  it('keeps a missing-regime stretch as its own null band instead of merging it', () => {
    const bands = regimeBands(['crisis', null, undefined, '', 'crisis'], {
      ...box,
      width: 140,
      padLeft: 20,
      padRight: 20,
    });
    // 5 slots over 100 wide → 20 each; the three flavours of "missing" coalesce
    expect(bands).toEqual([
      { regime: 'crisis', start: 0, end: 0, count: 1, x: 20, width: 20 },
      { regime: null, start: 1, end: 3, count: 3, x: 40, width: 60 },
      { regime: 'crisis', start: 4, end: 4, count: 1, x: 100, width: 20 },
    ]);
  });

  it('spans the whole plot with a single band for an all-one-regime run', () => {
    expect(regimeBands(['normal', 'normal'], box)).toEqual([
      { regime: 'normal', start: 0, end: 1, count: 2, x: 20, width: 80 },
    ]);
  });

  it('is empty for no cycles', () => {
    expect(regimeBands([], box)).toEqual([]);
  });
});

describe('drawdownSeries', () => {
  it('is zero at every new high and the exact fraction below the running peak', () => {
    expect(drawdownSeries([100, 110, 99, 121, 110])).toEqual([0, 0, -0.1, 0, -1 / 11]);
  });

  it('measures against the running peak, never a later one', () => {
    // the 50 is -50% of the FIRST peak; the recovery to 80 is still -20%
    expect(drawdownSeries([100, 50, 80])).toEqual([0, -0.5, -0.2]);
  });

  it('yields 0 for non-finite points without letting them move the peak', () => {
    expect(drawdownSeries([100, Number.NaN, 90])).toEqual([0, 0, -0.1]);
  });

  it('yields 0 while the peak is non-positive — no drawdown fraction of a zero base', () => {
    expect(drawdownSeries([-5, -10, 4, 2])).toEqual([0, 0, 0, -0.5]);
  });

  it('is empty for an empty series', () => {
    expect(drawdownSeries([])).toEqual([]);
  });
});
