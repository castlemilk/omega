/**
 * Pipeline — the one view the Polymarket shell has, and an honest account of
 * why it is the only one.
 *
 * Victoria's six tabs exist because the omega Go API serves Victoria's numbers.
 * Polymarket has no such thing: `internal/polymarket/client.go` is a Go client
 * for Polymarket's own API used by the node runtime, and neither
 * `cmd/omega-api` nor `internal/handler` registers a Connect service or a REST
 * route for it (checked 2026-08-18). So this shell declares **no data source**,
 * fetches nothing, and shows the operator the only thing that is actually
 * knowable from here — the pipeline the project is configured to run — plus a
 * named list of what a real shell would show once endpoints exist.
 *
 * The alternative was a tab full of plausible-looking zeroes. An empty state
 * that says "there is no backend" is worth more than a dashboard that implies
 * there is one and that it has nothing to report.
 */
import { Panel, Pill, SectionLabel } from '@omega-harness/usecase-kit/ui';
import type { UseCaseViewProps } from '@omega-harness/usecase-kit';

/**
 * The configured pipeline.
 *
 * ── Provenance ──────────────────────────────────────────────────────────────
 * Transcribed from `projects/polymarket.yaml` in the omega repo (flat form:
 * `id`/`name`/`domain`/`status`/`pipeline_config[]`/`eval_config`), read on
 * 2026-08-18. It is **hardcoded on purpose**. The harness has no build-time or
 * runtime dependency on the omega repo's files, there is no endpoint that
 * serves a project's pipeline, and inventing a YAML-fetching mechanism for one
 * static list would be a second, worse config seam. When a polymarket backend
 * exists, phase 2 replaces this constant with a real read — that is the whole
 * migration, and it is why the shape below mirrors the YAML's field names.
 *
 * `implementedBy` names the node module under `omega/nodes/polymarket/` that
 * runs the step. `RISK_MANAGEMENT` is a platform node shared with Victoria and
 * has no polymarket-specific module, which is itself worth showing.
 */
export interface PipelineStep {
  stepId: string;
  name: string;
  nodeType: string;
  description: string;
  order: number;
  implementedBy: string | null;
}

export const POLYMARKET_PIPELINE: readonly PipelineStep[] = [
  {
    stepId: 'step_1',
    name: 'WeatherData',
    nodeType: 'WEATHER_ENSEMBLE',
    description:
      'Fetch GEFS ensemble data and compute temperature exceedance probabilities',
    order: 1,
    implementedBy: 'weather_ensemble.py',
  },
  {
    stepId: 'step_2',
    name: 'MarketPricing',
    nodeType: 'POLYMARKET_PRICING',
    description: 'Fetch live weather market prices from Polymarket Gamma API',
    order: 2,
    implementedBy: 'pricing.py',
  },
  {
    stepId: 'step_3',
    name: 'EdgeDetection',
    nodeType: 'EDGE_DETECTION',
    description: 'Compare model probabilities vs market prices and flag edges',
    order: 3,
    implementedBy: 'edge_detection.py',
  },
  {
    stepId: 'step_4',
    name: 'RiskCheck',
    nodeType: 'RISK_MANAGEMENT',
    description: 'Validate position sizes via Kelly criterion',
    order: 4,
    implementedBy: null,
  },
  {
    stepId: 'step_5',
    name: 'VolArb',
    nodeType: 'VOL_ARB',
    description:
      'Implied-vol vs realized-vol arbitrage scanner (Christensen & Prabhala 1998)',
    order: 5,
    implementedBy: 'vol_arb.py',
  },
];

/**
 * The evaluation targets, from the same file's `eval_config`. Shown because
 * they are the only numbers in the project's configuration, and an operator
 * looking at a backend-less tab should at least learn what "working" means.
 */
export const POLYMARKET_TARGETS: readonly { metric: string; target: string }[] = [
  { metric: 'edge_accuracy', target: '0.60' },
  { metric: 'avg_edge', target: '0.08' },
];

/** What a real Polymarket shell shows, once something serves the data. */
const PHASE_TWO: readonly { title: string; detail: string }[] = [
  {
    title: 'Markets',
    detail:
      'The live weather markets being tracked, with token ids, resolution date and current book — the CLOB/Gamma reads that clob_client.py and pricing.py already make from Python.',
  },
  {
    title: 'Edge table',
    detail:
      'Model probability against market price per market, with the flagged edge and its Kelly-sized position — the output edge_detection.py computes and currently only writes to node state.',
  },
  {
    title: 'Weather ensemble',
    detail:
      'The GEFS member fan behind each exceedance probability, so an edge can be read back to the forecast that produced it rather than trusted as a scalar.',
  },
  {
    title: 'Bet ledger',
    detail:
      'Placed positions, fills and settled PnL against edge_accuracy and avg_edge — the Victoria Trades/Equity pair, for prediction markets.',
  },
];

function StepRow({ step }: { step: PipelineStep }) {
  return (
    <div className="flex items-start gap-3 border-b border-line px-4 py-3 last:border-b-0">
      <div
        className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full font-mono text-[10px] font-semibold text-canvas"
        style={{ background: 'var(--uc-accent)' }}
      >
        {step.order}
      </div>
      <div className="flex min-w-0 flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[12px] font-semibold text-ink">{step.name}</span>
          <span className="font-mono text-[9.5px] uppercase tracking-[.08em] text-faint">
            {step.nodeType}
          </span>
        </div>
        <p className="max-w-[74ch] text-[11px] leading-relaxed text-muted">{step.description}</p>
        <div className="font-mono text-[9.5px] text-ghost">
          {step.stepId} ·{' '}
          {step.implementedBy !== null
            ? `omega/nodes/polymarket/${step.implementedBy}`
            : 'shared platform node — no polymarket module'}
        </div>
      </div>
    </div>
  );
}

export function PolymarketPipeline({ state }: UseCaseViewProps) {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto bg-canvas px-6 py-5">
      <div className="mx-auto flex max-w-[1180px] flex-col gap-4">
        <div className="flex flex-col gap-1">
          <h2 className="text-[15px] font-semibold text-ink">Pipeline</h2>
          <p className="max-w-[74ch] text-[11.5px] leading-relaxed text-muted">
            The five steps <span className="font-mono">{state.objective.name}</span> is configured
            to run, from <span className="font-mono">projects/polymarket.yaml</span> in the omega
            repo. This is the configuration, not a live run — nothing on this page was fetched.
          </p>
        </div>

        <Panel>
          <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
            <SectionLabel>prediction_markets · 5 steps</SectionLabel>
            <Pill>autonomy: pico</Pill>
          </div>
          <div>
            {POLYMARKET_PIPELINE.map((step) => (
              <StepRow key={step.stepId} step={step} />
            ))}
          </div>
        </Panel>

        <Panel>
          <div className="border-b border-line px-4 py-2.5">
            <SectionLabel>eval targets</SectionLabel>
          </div>
          <div className="flex flex-wrap gap-3 p-4">
            {POLYMARKET_TARGETS.map((t) => (
              <div
                key={t.metric}
                className="flex min-w-[140px] flex-col gap-1.5 rounded-md border border-line bg-card px-3.5 py-3"
              >
                <SectionLabel>{t.metric}</SectionLabel>
                <div className="font-mono text-[17px] font-semibold tabular-nums text-ink3">
                  {t.target}
                </div>
                <div className="font-mono text-[9.5px] text-faint">target · not measured here</div>
              </div>
            ))}
          </div>
        </Panel>

        {/*
          The empty state. It names the missing backend precisely rather than
          saying "no data", because "no data" and "no endpoint" are different
          problems with different fixes, and only one of them is the operator's.
        */}
        <Panel>
          <div className="border-b border-line px-4 py-2.5">
            <SectionLabel>no backend yet</SectionLabel>
          </div>
          <div className="flex flex-col gap-3 p-4">
            <p className="max-w-[74ch] text-[11.5px] leading-relaxed text-muted">
              This shell declares no data source, so there is no health dot in the chrome and this
              tab issues no requests. The omega repo has a Polymarket Go client
              (<span className="font-mono">internal/polymarket/client.go</span>) and six Python
              nodes, but <span className="font-mono">cmd/omega-api</span> registers no Connect
              service and no REST route for any of them — there is nothing to read. Once there is,
              phase 2 is four views:
            </p>
            <div className="grid gap-2.5 sm:grid-cols-2">
              {PHASE_TWO.map((item) => (
                <div key={item.title} className="rounded-md border border-line bg-card px-3.5 py-3">
                  <div className="text-[11.5px] font-semibold text-ink2">{item.title}</div>
                  <p className="mt-1 text-[11px] leading-relaxed text-muted">{item.detail}</p>
                </div>
              ))}
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
}

