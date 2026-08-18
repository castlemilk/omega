/**
 * The Polymarket shell, on its own terms.
 *
 * Registration and tab derivation are asserted in the harness against the
 * generated roster (`apps/web/src/foreman/usecases/roster.test.ts`); this
 * repository has no host to register with. What is here is what the shell
 * decides: its manifest, and its one view.
 *
 * The Pipeline view is asserted on its *values*: the step list is the whole
 * content of the shell, it is a hand transcription of a YAML file in another
 * repo, and a test that only checked "five rows rendered" would pass while the
 * node types drifted from the file they claim to come from.
 */
import { describe, expect, it, vi } from 'vitest';
// `renderToStaticMarkup` rather than a DOM: the repo has no jsdom and no
// testing-library, and this view is static — there is nothing to click. Server
// rendering gives the same thing the assertions actually want, which is the
// text that reaches the operator, without adding a test environment to carry.
import { renderToStaticMarkup } from 'react-dom/server';
import type { ObjectiveState, UseCaseViewProps } from '@omega-harness/usecase-kit';
import { polymarketUseCase } from './index.js';
import { POLYMARKET_PIPELINE, POLYMARKET_TARGETS, PolymarketPipeline } from './views/Pipeline.js';

describe('the manifest', () => {
  it('declares no data source, because there is no backend to declare', () => {
    // Not an oversight and not a placeholder: nothing in omega serves
    // polymarket over HTTP. An aspirational source would put a permanently red
    // health dot in the chrome and teach the operator to ignore it.
    expect(polymarketUseCase.dataSources).toBeUndefined();
  });

  it('carries the violet accent, distinct from every status colour', () => {
    expect(polymarketUseCase.accent).toBe('#a67ff0');
  });

  it('renames nothing — the Foreman vocabulary already fits', () => {
    expect(polymarketUseCase.vocabulary).toBeUndefined();
  });

  it('takes its name from projects/polymarket.yaml', () => {
    expect(polymarketUseCase.name).toBe('Polymarket — prediction markets');
  });

  it('namespaces its one view id, so no core tab is shadowed', () => {
    expect(polymarketUseCase.views.map((v) => v.id)).toEqual(['polymarket-pipeline']);
    expect(polymarketUseCase.views[0].label).toBe('Pipeline');
  });
});

// The zero-requests guard lives in `./manifest-cost.test.ts`, not here: this
// file statically imports the manifest, so a dynamic re-import inside a test
// would return the cached module and the guard could never fail.

describe('the pipeline transcription', () => {
  it('carries the five steps of projects/polymarket.yaml, in order', () => {
    expect(POLYMARKET_PIPELINE.map((s) => [s.stepId, s.name, s.nodeType])).toEqual([
      ['step_1', 'WeatherData', 'WEATHER_ENSEMBLE'],
      ['step_2', 'MarketPricing', 'POLYMARKET_PRICING'],
      ['step_3', 'EdgeDetection', 'EDGE_DETECTION'],
      ['step_4', 'RiskCheck', 'RISK_MANAGEMENT'],
      ['step_5', 'VolArb', 'VOL_ARB'],
    ]);
    expect(POLYMARKET_PIPELINE.map((s) => s.order)).toEqual([1, 2, 3, 4, 5]);
  });

  it('attributes each step to a polymarket node module, or admits it is shared', () => {
    // RISK_MANAGEMENT is a platform node used by Victoria too — claiming a
    // polymarket module for it would be a lie the operator cannot check.
    expect(POLYMARKET_PIPELINE.find((s) => s.nodeType === 'RISK_MANAGEMENT')?.implementedBy).toBeNull();
    expect(
      POLYMARKET_PIPELINE.filter((s) => s.nodeType !== 'RISK_MANAGEMENT').map((s) => s.implementedBy),
    ).toEqual(['weather_ensemble.py', 'pricing.py', 'edge_detection.py', 'vol_arb.py']);
  });

  it('carries the eval targets from the same file', () => {
    expect(POLYMARKET_TARGETS).toEqual([
      { metric: 'edge_accuracy', target: '0.60' },
      { metric: 'avg_edge', target: '0.08' },
    ]);
  });
});

describe('the Pipeline view', () => {
  const state = {
    objective: { id: 'obj-1', name: 'Trade prediction markets' },
    harnesses: [],
    interventions: [],
    tickets: [],
  } as unknown as ObjectiveState;

  const props: UseCaseViewProps = {
    objectiveId: 'obj-1',
    state,
    focusId: null,
    onFocus: () => undefined,
    onOpenView: () => undefined,
    mutate: () => Promise.resolve(),
  };

  const markup = () => renderToStaticMarkup(<PolymarketPipeline {...props} />);

  it('renders every step by name, node type and description', () => {
    const html = markup();
    for (const step of POLYMARKET_PIPELINE) {
      expect(html).toContain(step.name);
      expect(html).toContain(step.nodeType);
      // Descriptions are transcribed prose; an entity-escaped one would still
      // be correct, so compare on the escaped form React actually emits.
      expect(html).toContain(step.description.replace(/&/g, '&amp;'));
      expect(html).toContain(`>${String(step.order)}</div>`);
    }
  });

  it('attributes each step to its node module, or says the node is shared', () => {
    const html = markup();
    expect(html).toContain('omega/nodes/polymarket/weather_ensemble.py');
    expect(html).toContain('shared platform node — no polymarket module');
  });

  it('names the objective and the file the steps came from', () => {
    const html = markup();
    expect(html).toContain('Trade prediction markets');
    expect(html).toContain('projects/polymarket.yaml');
  });

  it('renders the eval targets as targets, not as measurements', () => {
    const html = markup();
    expect(html).toContain('edge_accuracy');
    expect(html).toContain('0.60');
    expect(html).toContain('target · not measured here');
  });

  it('says there is no backend, and names what would replace this', () => {
    const html = markup();
    expect(html).toContain('no backend yet');
    expect(html).toContain('registers no Connect');
    for (const title of ['Markets', 'Edge table', 'Weather ensemble', 'Bet ledger']) {
      expect(html).toContain(`>${title}</div>`);
    }
  });

  it('fetches nothing when the view actually renders', () => {
    // The stronger form of the manifest test: not just "registering is free"
    // but "opening the tab is free". With no data source there is nothing to
    // call, and this is what keeps it that way.
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    markup();
    expect(fetchSpy).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});

