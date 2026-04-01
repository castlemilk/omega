// DECISION TRACE — per-cycle reasoning chain for Victoria's trading engine
// Shows: signal outputs → composites → demeaning → conviction → proposals → filters → trades
import { useEffect, useState, useCallback } from "react";
import {
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import {
  GitBranch,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  Filter,
  TrendingUp,
  TrendingDown,
  Minus,
  CheckCircle,
  XCircle,
} from "lucide-react";

const BASE = "";
const TOOLTIP_STYLE = {
  background: "#1f2937",
  border: "1px solid #374151",
  borderRadius: 6,
  fontSize: 11,
};
const TICK_STYLE = { fontSize: 10, fill: "#6b7280" };

// ── Types ──────────────────────────────────────────────────────────────────────

interface SignalTrace {
  signal_name: string;
  raw_value: number;
  rationale_text: string;
  inputs_used: Record<string, unknown>;
  weight_applied: number;
}

interface TickerDecision {
  ticker: string;
  signal_traces: SignalTrace[];
  raw_composite: number;
  basket_mean: number;
  demeaned_composite: number;
  conviction: string;
  conviction_score: number;
  proposal: string;
  filters_applied: string[];
  final_action: string;
  filter_reason: string;
}

interface DecisionPayload {
  cycle: number;
  timestamp: string;
  version: string;
  regime: string;
  regime_confidence: number;
  regime_hmm: string;
  sit_out_reason: string;
  sit_out_size_mult: number;
  fiedler_scale: number;
  fiedler_regime: string;
  per_ticker: Record<string, TickerDecision>;
  n_trades: number;
  n_filtered: number;
  n_hold: number;
}

interface DecisionRow {
  id: number;
  cycle: number;
  version: string;
  regime: string;
  sit_out: string;
  recorded_at: string;
  payload: DecisionPayload;
}

// ── Color helpers ──────────────────────────────────────────────────────────────

function signalColor(value: number): string {
  if (value > 0.3) return "#22c55e";
  if (value > 0.05) return "#86efac";
  if (value < -0.3) return "#ef4444";
  if (value < -0.05) return "#fca5a5";
  return "#6b7280";
}

function convictionBadge(conviction: string): { bg: string; text: string } {
  switch (conviction) {
    case "STRONG_BUY":
      return { bg: "bg-emerald-900/50 border border-emerald-700", text: "text-emerald-400" };
    case "BUY":
      return { bg: "bg-green-900/50 border border-green-700", text: "text-green-400" };
    case "HOLD":
      return { bg: "bg-gray-800/50 border border-gray-600", text: "text-gray-400" };
    case "SELL":
      return { bg: "bg-red-900/50 border border-red-700", text: "text-red-400" };
    case "STRONG_SELL":
      return { bg: "bg-rose-900/50 border border-rose-700", text: "text-rose-400" };
    default:
      return { bg: "bg-gray-800/50 border border-gray-600", text: "text-gray-400" };
  }
}

function actionBadge(action: string): string {
  switch (action) {
    case "TRADE":
      return "bg-emerald-900/60 text-emerald-300 border border-emerald-700";
    case "FILTERED":
      return "bg-amber-900/60 text-amber-300 border border-amber-700";
    case "HOLD":
      return "bg-gray-800/60 text-gray-400 border border-gray-600";
    case "SIT_OUT":
      return "bg-blue-900/60 text-blue-300 border border-blue-700";
    default:
      return "bg-gray-800/60 text-gray-400 border border-gray-600";
  }
}

function regimePill(regime: string): string {
  const r = regime.toUpperCase();
  if (r === "BULL") return "bg-emerald-900/50 text-emerald-400 border border-emerald-700";
  if (r === "BEAR") return "bg-red-900/50 text-red-400 border border-red-700";
  if (r === "SIDEWAYS") return "bg-yellow-900/50 text-yellow-400 border border-yellow-700";
  return "bg-gray-800/50 text-gray-400 border border-gray-600";
}

// ── Signal heatmap row ─────────────────────────────────────────────────────────

function SignalRow({ trace }: { trace: SignalTrace }) {
  const [expanded, setExpanded] = useState(false);
  const barColor = signalColor(trace.raw_value);
  const barWidth = Math.abs(trace.raw_value) * 100;
  const isPositive = trace.raw_value >= 0;

  return (
    <div className="border-b border-surface-700 last:border-0">
      <button
        className="w-full flex items-center gap-3 px-3 py-2 hover:bg-surface-700/40 text-left"
        onClick={() => setExpanded((e) => !e)}
      >
        <span className="text-xs font-mono text-gray-400 w-36 shrink-0">{trace.signal_name}</span>
        {/* Mini bar */}
        <div className="flex-1 flex items-center gap-2">
          <div className="w-32 h-2 bg-surface-700 rounded overflow-hidden flex">
            {isPositive ? (
              <>
                <div className="w-1/2" />
                <div
                  className="h-full rounded"
                  style={{ width: `${barWidth / 2}%`, backgroundColor: barColor }}
                />
              </>
            ) : (
              <>
                <div
                  className="h-full rounded ml-auto"
                  style={{
                    width: `${barWidth / 2}%`,
                    backgroundColor: barColor,
                    marginLeft: `${50 - barWidth / 2}%`,
                  }}
                />
                <div className="w-1/2" />
              </>
            )}
          </div>
          <span
            className="text-xs font-mono tabular-nums w-14 text-right"
            style={{ color: barColor }}
          >
            {trace.raw_value >= 0 ? "+" : ""}
            {trace.raw_value.toFixed(3)}
          </span>
          <span className="text-xs text-gray-500 flex-1 truncate">{trace.rationale_text}</span>
        </div>
        {expanded ? (
          <ChevronDown className="w-3 h-3 text-gray-500 shrink-0" />
        ) : (
          <ChevronRight className="w-3 h-3 text-gray-500 shrink-0" />
        )}
      </button>
      {expanded && (
        <div className="px-6 pb-2 text-xs text-gray-400 space-y-1 bg-surface-900/30">
          <p className="text-gray-300 font-medium">{trace.rationale_text}</p>
          {Object.keys(trace.inputs_used).length > 0 && (
            <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 mt-1">
              {Object.entries(trace.inputs_used).map(([k, v]) => (
                <span key={k} className="font-mono text-gray-500">
                  {k}:{" "}
                  <span className="text-gray-300">
                    {typeof v === "number" ? v.toFixed(4) : String(v)}
                  </span>
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Filter funnel ──────────────────────────────────────────────────────────────

function FilterFunnel({ filters }: { filters: string[] }) {
  return (
    <div className="space-y-1 mt-2">
      {filters.map((f, i) => {
        const isBlocked = f.includes(":blocked") || f.includes(":hold");
        const isPass = f.includes(":pass") || f.includes("→");
        return (
          <div key={i} className="flex items-center gap-2 text-xs">
            {isBlocked ? (
              <XCircle className="w-3 h-3 text-red-400 shrink-0" />
            ) : isPass ? (
              <CheckCircle className="w-3 h-3 text-emerald-400 shrink-0" />
            ) : (
              <div className="w-3 h-3 rounded-full bg-gray-600 shrink-0" />
            )}
            <span className={isBlocked ? "text-red-300" : isPass ? "text-emerald-300" : "text-gray-400"}>
              {f}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ── Ticker decision card ───────────────────────────────────────────────────────

function TickerCard({ decision }: { decision: TickerDecision }) {
  const [expanded, setExpanded] = useState(false);
  const badge = convictionBadge(decision.conviction);
  const actionCls = actionBadge(decision.final_action);
  const ticker = decision.ticker.replace("USDT", "").replace("/USDT", "");

  const compositeColor = signalColor(decision.raw_composite);
  const demeanedColor = signalColor(decision.demeaned_composite);

  const icon =
    decision.proposal === "LONG" ? (
      <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
    ) : decision.proposal === "SHORT" ? (
      <TrendingDown className="w-3.5 h-3.5 text-red-400" />
    ) : (
      <Minus className="w-3.5 h-3.5 text-gray-500" />
    );

  return (
    <div className="border border-surface-600 rounded-lg overflow-hidden">
      {/* Header row */}
      <button
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-surface-700/40 text-left"
        onClick={() => setExpanded((e) => !e)}
      >
        <span className="font-bold text-sm text-white w-10 shrink-0">{ticker}</span>
        {icon}
        <span className={`text-xs px-2 py-0.5 rounded font-medium ${badge.bg} ${badge.text}`}>
          {decision.conviction}
        </span>
        <span className={`text-xs px-2 py-0.5 rounded font-medium ${actionCls}`}>
          {decision.final_action}
        </span>
        <div className="flex-1 flex items-center gap-4 justify-end text-xs font-mono">
          <span className="text-gray-500">
            composite{" "}
            <span style={{ color: compositeColor }}>
              {decision.raw_composite >= 0 ? "+" : ""}
              {decision.raw_composite.toFixed(3)}
            </span>
          </span>
          <span className="text-gray-500">
            demeaned{" "}
            <span style={{ color: demeanedColor }}>
              {decision.demeaned_composite >= 0 ? "+" : ""}
              {decision.demeaned_composite.toFixed(3)}
            </span>
          </span>
          <span className="text-gray-500 text-xs truncate max-w-xs">
            {decision.filter_reason && (
              <span className="text-amber-400">blocked: {decision.filter_reason}</span>
            )}
          </span>
        </div>
        {expanded ? (
          <ChevronDown className="w-4 h-4 text-gray-500 shrink-0" />
        ) : (
          <ChevronRight className="w-4 h-4 text-gray-500 shrink-0" />
        )}
      </button>

      {expanded && (
        <div className="border-t border-surface-600 grid grid-cols-2 gap-0 divide-x divide-surface-600">
          {/* Left: signal traces */}
          <div>
            <div className="px-3 py-1.5 bg-surface-800/50 text-xs font-semibold text-gray-400 uppercase tracking-wide">
              Signal Traces ({decision.signal_traces.length})
            </div>
            {decision.signal_traces.length === 0 ? (
              <p className="px-4 py-3 text-xs text-gray-500 italic">No signal traces recorded</p>
            ) : (
              decision.signal_traces.map((t) => <SignalRow key={t.signal_name} trace={t} />)
            )}
          </div>
          {/* Right: filter chain */}
          <div className="px-4 py-3">
            <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
              Filter Chain
            </div>
            <FilterFunnel filters={decision.filters_applied} />
            <div className="mt-3 pt-3 border-t border-surface-600 space-y-1 text-xs">
              <div className="flex justify-between">
                <span className="text-gray-500">IC-weighted conviction</span>
                <span
                  className="font-mono"
                  style={{ color: signalColor(decision.conviction_score) }}
                >
                  {decision.conviction_score >= 0 ? "+" : ""}
                  {decision.conviction_score.toFixed(3)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">basket mean</span>
                <span className="font-mono text-gray-400">{decision.basket_mean.toFixed(3)}</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Signal contribution heatmap (cycle-level) ──────────────────────────────────

function SignalHeatmap({ payload }: { payload: DecisionPayload }) {
  // Aggregate signal values across all tickers
  const signalMap: Record<string, number[]> = {};
  for (const td of Object.values(payload.per_ticker)) {
    for (const trace of td.signal_traces) {
      if (!signalMap[trace.signal_name]) signalMap[trace.signal_name] = [];
      signalMap[trace.signal_name].push(trace.raw_value);
    }
  }
  const data = Object.entries(signalMap).map(([name, vals]) => ({
    name: name.replace("_signal", "").replace("_", " "),
    avg: +(vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(3),
    count: vals.length,
  }));
  if (!data.length) return null;

  return (
    <div className="mb-6">
      <h3 className="text-sm font-semibold text-gray-300 mb-2">Signal Contribution Heatmap</h3>
      <ResponsiveContainer width="100%" height={120}>
        <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis dataKey="name" tick={TICK_STYLE} />
          <YAxis domain={[-1, 1]} tick={TICK_STYLE} width={30} />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Bar dataKey="avg" name="Avg Value" radius={[2, 2, 0, 0]}>
            {data.map((d, i) => (
              <Cell key={i} fill={signalColor(d.avg)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Filter funnel summary ──────────────────────────────────────────────────────

function FunnelSummary({ payload }: { payload: DecisionPayload }) {
  const tickers = Object.values(payload.per_ticker);
  const total = tickers.length;
  const traded = tickers.filter((t) => t.final_action === "TRADE").length;
  const filtered = tickers.filter((t) => t.final_action === "FILTERED").length;
  const held = tickers.filter((t) => t.final_action === "HOLD").length;

  const filterReasons: Record<string, number> = {};
  for (const t of tickers.filter((td) => td.filter_reason)) {
    const key = t.filter_reason.split("(")[0];
    filterReasons[key] = (filterReasons[key] || 0) + 1;
  }

  return (
    <div className="mb-6">
      <h3 className="text-sm font-semibold text-gray-300 mb-2">Filter Funnel</h3>
      <div className="flex gap-4 flex-wrap mb-3">
        <div className="bg-surface-800 rounded-lg px-4 py-2 text-center">
          <p className="text-xl font-bold text-gray-200">{total}</p>
          <p className="text-xs text-gray-500">Total Tickers</p>
        </div>
        <div className="bg-surface-800 rounded-lg px-4 py-2 text-center">
          <p className="text-xl font-bold text-emerald-400">{traded}</p>
          <p className="text-xs text-gray-500">Traded</p>
        </div>
        <div className="bg-surface-800 rounded-lg px-4 py-2 text-center">
          <p className="text-xl font-bold text-amber-400">{filtered}</p>
          <p className="text-xs text-gray-500">Filtered</p>
        </div>
        <div className="bg-surface-800 rounded-lg px-4 py-2 text-center">
          <p className="text-xl font-bold text-gray-400">{held}</p>
          <p className="text-xs text-gray-500">HOLD</p>
        </div>
      </div>
      {Object.keys(filterReasons).length > 0 && (
        <div className="flex flex-wrap gap-2">
          {Object.entries(filterReasons).map(([reason, count]) => (
            <span
              key={reason}
              className="text-xs px-2 py-0.5 rounded bg-amber-900/40 text-amber-300 border border-amber-800"
            >
              {reason}: {count}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Cycle detail view ──────────────────────────────────────────────────────────

function CycleDetail({ row, onBack }: { row: DecisionRow; onBack: () => void }) {
  const p = row.payload;
  const tickers = Object.values(p.per_ticker).sort((a, b) => {
    const actionOrder: Record<string, number> = { TRADE: 0, FILTERED: 1, HOLD: 2 };
    return (actionOrder[a.final_action] ?? 3) - (actionOrder[b.final_action] ?? 3);
  });

  return (
    <div>
      {/* Back + header */}
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-sm text-gray-400 hover:text-white transition-colors"
        >
          <ChevronRight className="w-4 h-4 rotate-180" />
          Back
        </button>
        <div>
          <h2 className="text-xl font-bold text-white">Cycle {p.cycle} Decision Trace</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            {new Date(p.timestamp).toLocaleString()} · version {p.version}
          </p>
        </div>
      </div>

      {/* Regime + context bar */}
      <div className="flex flex-wrap gap-3 mb-6">
        <span className={`text-xs px-3 py-1 rounded-full font-semibold border ${regimePill(p.regime)}`}>
          {p.regime.toUpperCase()} {p.regime_confidence > 0 && `(conf ${(p.regime_confidence * 100).toFixed(0)}%)`}
        </span>
        {p.sit_out_reason && p.sit_out_reason !== "normal" && (
          <span className="text-xs px-3 py-1 rounded-full bg-blue-900/50 text-blue-300 border border-blue-700">
            SIT-OUT: {p.sit_out_reason}
          </span>
        )}
        <span className="text-xs px-3 py-1 rounded-full bg-surface-800 text-gray-400 border border-surface-600">
          Fiedler: {p.fiedler_regime} ({p.fiedler_scale.toFixed(2)})
        </span>
        <span className="text-xs px-3 py-1 rounded-full bg-emerald-900/30 text-emerald-400 border border-emerald-800">
          {p.n_trades} trades
        </span>
        <span className="text-xs px-3 py-1 rounded-full bg-amber-900/30 text-amber-400 border border-amber-800">
          {p.n_filtered} filtered
        </span>
      </div>

      {/* Signal heatmap */}
      <SignalHeatmap payload={p} />

      {/* Filter funnel */}
      <FunnelSummary payload={p} />

      {/* Per-ticker decisions */}
      <h3 className="text-sm font-semibold text-gray-300 mb-3">
        Per-Ticker Decisions ({tickers.length})
      </h3>
      <div className="space-y-2">
        {tickers.map((td) => (
          <TickerCard key={td.ticker} decision={td} />
        ))}
        {tickers.length === 0 && (
          <p className="text-sm text-gray-500 italic">
            No per-ticker decisions recorded for this cycle.
          </p>
        )}
      </div>
    </div>
  );
}

// ── Cycle list ─────────────────────────────────────────────────────────────────

function CycleListRow({ row, onClick }: { row: DecisionRow; onClick: () => void }) {
  const p = row.payload;
  const tickers = Object.values(p.per_ticker);
  const traded = tickers.filter((t) => t.final_action === "TRADE").length;
  const filtered = tickers.filter((t) => t.final_action === "FILTERED").length;

  return (
    <button
      onClick={onClick}
      className="w-full flex items-center gap-4 px-4 py-3 border border-surface-600 rounded-lg hover:border-surface-500 hover:bg-surface-700/40 text-left transition-colors"
    >
      <span className="text-sm font-bold text-white w-16 shrink-0">C-{p.cycle}</span>
      <span
        className={`text-xs px-2 py-0.5 rounded font-semibold border w-20 text-center shrink-0 ${regimePill(p.regime)}`}
      >
        {(p.regime || "?").toUpperCase()}
      </span>
      {p.sit_out_reason && p.sit_out_reason !== "normal" ? (
        <span className="text-xs px-2 py-0.5 rounded bg-blue-900/50 text-blue-300 border border-blue-700 shrink-0">
          SIT-OUT
        </span>
      ) : (
        <span className="text-xs text-emerald-400 font-semibold shrink-0">
          {traded > 0 ? `${traded} trade${traded > 1 ? "s" : ""}` : "no trades"}
        </span>
      )}
      <span className="text-xs text-amber-400 shrink-0">
        {filtered > 0 && `${filtered} filtered`}
      </span>
      <span className="flex-1 text-xs text-gray-500 truncate">
        {tickers
          .slice(0, 4)
          .map((t) => t.ticker.replace("USDT", ""))
          .join(" · ")}
        {tickers.length > 4 && ` +${tickers.length - 4}`}
      </span>
      <span className="text-xs text-gray-600 shrink-0">
        {new Date(row.recorded_at).toLocaleTimeString()}
      </span>
      <ChevronRight className="w-4 h-4 text-gray-500 shrink-0" />
    </button>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function DecisionTrace() {
  const [decisions, setDecisions] = useState<DecisionRow[]>([]);
  const [selected, setSelected] = useState<DecisionRow | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [limit, setLimit] = useState(50);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${BASE}/api/v1/dashboard/decisions?limit=${limit}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setDecisions(json.decisions ?? []);
    } catch (e) {
      setError(String(e));
      setDecisions([]);
    } finally {
      setLoading(false);
    }
  }, [limit]);

  useEffect(() => {
    load();
  }, [load]);

  if (selected) {
    return (
      <div className="max-w-5xl mx-auto">
        <CycleDetail row={selected} onBack={() => setSelected(null)} />
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto">
      {/* Page header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <GitBranch className="w-5 h-5 text-indigo-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Decision Trace</h1>
            <p className="text-xs text-gray-500 mt-0.5">
              Full reasoning chain per cycle — signals → composite → conviction → filters → trades
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="text-xs bg-surface-800 border border-surface-600 rounded px-2 py-1.5 text-gray-300"
          >
            <option value={20}>Last 20</option>
            <option value={50}>Last 50</option>
            <option value={100}>Last 100</option>
            <option value={200}>Last 200</option>
          </select>
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-surface-800 border border-surface-600 rounded hover:bg-surface-700 text-gray-300 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* Stats bar */}
      {decisions.length > 0 && (
        <div className="grid grid-cols-4 gap-3 mb-6">
          {[
            { label: "Cycles", value: decisions.length },
            {
              label: "With Trades",
              value: decisions.filter((d) => d.payload.n_trades > 0).length,
            },
            {
              label: "Sit-Outs",
              value: decisions.filter(
                (d) => d.payload.sit_out_reason && d.payload.sit_out_reason !== "normal"
              ).length,
            },
            {
              label: "Latest Cycle",
              value: decisions[0]?.cycle ?? "—",
            },
          ].map((s) => (
            <div key={s.label} className="bg-surface-800 rounded-lg px-4 py-3">
              <p className="text-xl font-bold text-white">{s.value}</p>
              <p className="text-xs text-gray-500 mt-0.5">{s.label}</p>
            </div>
          ))}
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="mb-4 px-4 py-3 bg-red-900/30 border border-red-700 rounded-lg text-sm text-red-300">
          {error.includes("404") || error.includes("Failed") || error.includes("500")
            ? "No decision data yet — start a training run (`python scripts/run_training.py`) and decision traces will appear here."
            : error}
        </div>
      )}

      {/* Loading */}
      {loading && decisions.length === 0 && (
        <div className="text-center py-16 text-gray-500 text-sm">Loading decision traces…</div>
      )}

      {/* Empty state */}
      {!loading && !error && decisions.length === 0 && (
        <div className="text-center py-16">
          <GitBranch className="w-10 h-10 text-gray-600 mx-auto mb-3" />
          <p className="text-gray-400 font-medium">No decision traces yet</p>
          <p className="text-sm text-gray-600 mt-1">
            Start a training run — each cycle will record the full reasoning chain here.
          </p>
        </div>
      )}

      {/* Cycle list */}
      {decisions.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 mb-3">
            <Filter className="w-3.5 h-3.5 text-gray-500" />
            <span className="text-xs text-gray-500">
              {decisions.length} cycle{decisions.length !== 1 ? "s" : ""} — click to drill into the
              reasoning chain
            </span>
          </div>
          {decisions.map((row) => (
            <CycleListRow key={row.id} row={row} onClick={() => setSelected(row)} />
          ))}
        </div>
      )}
    </div>
  );
}
