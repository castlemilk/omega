// GEOMETRY VIEW — Information geometry market manifold dashboard
// Ricci curvature, geodesic distances, market state scatter
import { useEffect, useState, useCallback } from "react";
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
  LineChart,
  Line,
  RadialBarChart,
  RadialBar,
  PolarAngleAxis,
  ReferenceLine,
  Legend,
} from "recharts";
import { GitMerge, TrendingUp, TrendingDown, Minus, RefreshCw } from "lucide-react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ManifoldPoint {
  cycle: number;
  ricci: number;
  mu: number;
  variance: number;
  skewness: number;
  regime: "mean_reversion" | "trending" | "transitional";
  geo_dist_crash?: number;
  geo_dist_rally?: number;
  signal?: number;
}

interface ManifoldSummary {
  current_ricci: number;
  current_regime: string;
  current_signal: number;
  geo_dist_crash: number;
  geo_dist_rally: number;
  geo_dist_neutral: number;
  confidence: number;
  history: ManifoldPoint[];
}

// ── Constants ─────────────────────────────────────────────────────────────────

const GRID_COLOR = "#374151";
const TICK_STYLE = { fontSize: 10, fill: "#6b7280" };
const TOOLTIP_STYLE = {
  background: "#111827",
  border: "1px solid #374151",
  borderRadius: 6,
  fontSize: 11,
};

function regimeColor(regime: string): string {
  if (regime === "trending") return "#f97316";       // orange — momentum
  if (regime === "mean_reversion") return "#3b82f6"; // blue — mean-revert
  return "#6b7280";                                   // grey — transitional
}

function ricciColor(r: number): string {
  if (r > 0.3) return "#3b82f6";
  if (r < -0.3) return "#f97316";
  return "#6b7280";
}

// ── Mock / fallback data (used when API is unavailable) ───────────────────────

function generateMockHistory(n = 60): ManifoldPoint[] {
  const points: ManifoldPoint[] = [];
  let ricci = 0.1;
  for (let i = 0; i < n; i++) {
    ricci = ricci * 0.85 + (Math.random() - 0.5) * 1.2;
    ricci = Math.max(-5, Math.min(5, ricci));
    const regime: ManifoldPoint["regime"] =
      ricci > 0.3 ? "mean_reversion" : ricci < -0.3 ? "trending" : "transitional";
    points.push({
      cycle: i + 1,
      ricci: parseFloat(ricci.toFixed(3)),
      mu: parseFloat((Math.random() * 0.02 - 0.01).toFixed(5)),
      variance: parseFloat((Math.abs(Math.random() * 0.002)).toFixed(6)),
      skewness: parseFloat((Math.random() * 2 - 1).toFixed(3)),
      regime,
      geo_dist_crash: parseFloat((Math.random() * 3 + 0.5).toFixed(3)),
      geo_dist_rally: parseFloat((Math.random() * 3 + 0.5).toFixed(3)),
      signal: parseFloat((Math.tanh(ricci * 0.5)).toFixed(3)),
    });
  }
  return points;
}

function buildMockSummary(): ManifoldSummary {
  const history = generateMockHistory(60);
  const latest = history[history.length - 1];
  return {
    current_ricci: latest.ricci,
    current_regime: latest.regime,
    current_signal: latest.signal ?? 0,
    geo_dist_crash: latest.geo_dist_crash ?? 1.8,
    geo_dist_rally: latest.geo_dist_rally ?? 2.4,
    geo_dist_neutral: 0.9,
    confidence: 0.72,
    history,
  };
}

// ── Gauge component ───────────────────────────────────────────────────────────

function CurvatureGauge({ ricci, regime }: { ricci: number; regime: string }) {
  // Normalise ricci ∈ [-5, 5] → [0, 100] for gauge display
  const pct = Math.round(((ricci + 5) / 10) * 100);
  const color = ricciColor(ricci);
  const data = [{ name: "curvature", value: pct, fill: color }];

  return (
    <div className="flex flex-col items-center gap-1">
      <div className="w-40 h-40">
        <ResponsiveContainer width="100%" height="100%">
          <RadialBarChart
            cx="50%"
            cy="50%"
            innerRadius="60%"
            outerRadius="90%"
            barSize={14}
            data={data}
            startAngle={180}
            endAngle={0}
          >
            <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
            <RadialBar dataKey="value" cornerRadius={6} background={{ fill: "#1f2937" }} />
          </RadialBarChart>
        </ResponsiveContainer>
      </div>
      <div className="text-center -mt-6">
        <div className="text-xl font-mono font-bold" style={{ color }}>
          {ricci >= 0 ? "+" : ""}
          {ricci.toFixed(2)}
        </div>
        <div className="text-xs text-gray-500 uppercase tracking-wider">{regime.replace("_", " ")}</div>
      </div>
    </div>
  );
}

// ── Regime icon ───────────────────────────────────────────────────────────────

function RegimeIcon({ regime }: { regime: string }) {
  if (regime === "trending") return <TrendingUp size={14} className="text-orange-400" />;
  if (regime === "mean_reversion") return <TrendingDown size={14} className="text-blue-400" />;
  return <Minus size={14} className="text-gray-500" />;
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function GeometryView() {
  const [summary, setSummary] = useState<ManifoldSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
    try {
      // Attempt to load from the training API — geometry endpoint (Go API)
      const res = await fetch("/api/victoria/geometry");
      if (res.ok) {
        const data = await res.json();
        setSummary(data);
      } else {
        // API not yet wired — use mock data for visualisation development
        setSummary(buildMockSummary());
      }
    } catch {
      setSummary(buildMockSummary());
    } finally {
      setLoading(false);
      setLastUpdated(new Date());
    }
  }, []);

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 30_000);
    return () => clearInterval(id);
  }, [fetchData]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-500 text-sm">
        Loading manifold state…
      </div>
    );
  }

  if (!summary) return null;

  const { history, current_ricci, current_regime, current_signal, geo_dist_crash, geo_dist_rally, geo_dist_neutral, confidence } = summary;

  // Scatter data: (skewness, mu) coloured by Ricci curvature
  const scatterData = history.map((p) => ({
    x: p.skewness,
    y: p.mu * 1000, // scale μ for visibility (×1000 = per-mille)
    ricci: p.ricci,
    regime: p.regime,
    cycle: p.cycle,
  }));

  // Geodesic distance timeline
  const geoData = history.map((p) => ({
    cycle: p.cycle,
    crash: p.geo_dist_crash ?? 0,
    rally: p.geo_dist_rally ?? 0,
  }));

  // Signal timeline
  const signalData = history.map((p) => ({
    cycle: p.cycle,
    ricci: p.ricci,
    signal: p.signal ?? 0,
  }));

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <GitMerge size={20} className="text-indigo-400" />
          <div>
            <h1 className="text-lg font-semibold text-gray-100">Market Manifold</h1>
            <p className="text-xs text-gray-500">
              Information geometry — Ricci curvature, geodesic distances, manifold state
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="text-xs text-gray-600">
              {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={fetchData}
            className="p-1.5 rounded hover:bg-gray-800 text-gray-500 hover:text-gray-300 transition-colors"
          >
            <RefreshCw size={14} />
          </button>
        </div>
      </div>

      {/* Top stat row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          label="Ricci Curvature"
          value={`${current_ricci >= 0 ? "+" : ""}${current_ricci.toFixed(3)}`}
          sub={current_regime.replace("_", " ")}
          color={ricciColor(current_ricci)}
        />
        <StatCard
          label="Geometry Signal"
          value={`${current_signal >= 0 ? "+" : ""}${current_signal.toFixed(3)}`}
          sub={current_signal > 0.1 ? "bullish" : current_signal < -0.1 ? "bearish" : "neutral"}
          color={current_signal > 0.1 ? "#22c55e" : current_signal < -0.1 ? "#ef4444" : "#6b7280"}
        />
        <StatCard
          label="Distance → Crash"
          value={geo_dist_crash.toFixed(3)}
          sub={geo_dist_crash < 1.0 ? "near crash" : "away"}
          color={geo_dist_crash < 1.0 ? "#ef4444" : "#9ca3af"}
        />
        <StatCard
          label="Confidence"
          value={`${(confidence * 100).toFixed(0)}%`}
          sub={confidence >= 0.5 ? "active" : "warming up"}
          color={confidence >= 0.5 ? "#22c55e" : "#f59e0b"}
        />
      </div>

      {/* Main grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Curvature gauge */}
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 flex flex-col items-center justify-center gap-3">
          <div className="text-xs text-gray-500 uppercase tracking-wider">Ricci Scalar R</div>
          <CurvatureGauge ricci={current_ricci} regime={current_regime} />
          <div className="text-center text-xs text-gray-500 max-w-[160px]">
            {current_regime === "mean_reversion" &&
              "Positive curvature: market is mean-reverting. Fade extremes."}
            {current_regime === "trending" &&
              "Negative curvature: momentum regime. Follow the trend."}
            {current_regime === "transitional" &&
              "Near-zero curvature: regime transition. Reduce size."}
          </div>
          <div className="flex items-center gap-1.5 text-xs">
            <RegimeIcon regime={current_regime} />
            <span
              className="font-medium capitalize"
              style={{ color: regimeColor(current_regime) }}
            >
              {current_regime.replace("_", " ")}
            </span>
          </div>
          <div className="flex gap-4 text-xs text-gray-500 mt-1">
            <span>crash Δ {geo_dist_crash.toFixed(2)}</span>
            <span>rally Δ {geo_dist_rally.toFixed(2)}</span>
            <span>neutral Δ {geo_dist_neutral.toFixed(2)}</span>
          </div>
        </div>

        {/* Market state scatter */}
        <div className="lg:col-span-2 bg-gray-900 border border-gray-800 rounded-lg p-4">
          <div className="text-xs text-gray-500 uppercase tracking-wider mb-3">
            Market State Scatter — (skewness, μ×1000) coloured by Ricci curvature
          </div>
          <ResponsiveContainer width="100%" height={220}>
            <ScatterChart margin={{ top: 4, right: 12, left: -8, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} />
              <XAxis
                dataKey="x"
                type="number"
                name="skewness"
                domain={["auto", "auto"]}
                tick={TICK_STYLE}
                label={{ value: "skewness", position: "insideBottom", offset: -2, fontSize: 9, fill: "#6b7280" }}
              />
              <YAxis
                dataKey="y"
                type="number"
                name="μ (×1000)"
                domain={["auto", "auto"]}
                tick={TICK_STYLE}
                label={{ value: "μ×1k", angle: -90, position: "insideLeft", offset: 8, fontSize: 9, fill: "#6b7280" }}
              />
              <Tooltip
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const d = payload[0].payload;
                  return (
                    <div style={TOOLTIP_STYLE} className="px-2 py-1.5">
                      <div className="text-gray-300">cycle {d.cycle}</div>
                      <div style={{ color: regimeColor(d.regime) }}>{d.regime.replace("_", " ")}</div>
                      <div className="text-gray-400">R = {d.ricci.toFixed(3)}</div>
                      <div className="text-gray-400">skew = {d.x?.toFixed(3)}</div>
                      <div className="text-gray-400">μ = {(d.y / 1000).toFixed(5)}</div>
                    </div>
                  );
                }}
              />
              <Scatter data={scatterData} name="states">
                {scatterData.map((entry, i) => (
                  <Cell key={i} fill={ricciColor(entry.ricci)} opacity={0.75} />
                ))}
              </Scatter>
            </ScatterChart>
          </ResponsiveContainer>
          {/* Legend */}
          <div className="flex gap-4 text-xs text-gray-500 mt-2 justify-center">
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-500 inline-block" /> mean-reversion (R&gt;0)</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-orange-500 inline-block" /> trending (R&lt;0)</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-gray-500 inline-block" /> transitional</span>
          </div>
        </div>
      </div>

      {/* Ricci + signal timeline */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div className="text-xs text-gray-500 uppercase tracking-wider mb-3">
          Ricci Curvature &amp; Signal — rolling history
        </div>
        <ResponsiveContainer width="100%" height={160}>
          <LineChart data={signalData} margin={{ top: 4, right: 12, left: -8, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} />
            <XAxis dataKey="cycle" tick={TICK_STYLE} />
            <YAxis domain={[-5.5, 5.5]} tick={TICK_STYLE} />
            <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={{ color: "#9ca3af" }} />
            <ReferenceLine y={0.3} stroke="#3b82f6" strokeDasharray="4 2" strokeOpacity={0.5} />
            <ReferenceLine y={-0.3} stroke="#f97316" strokeDasharray="4 2" strokeOpacity={0.5} />
            <ReferenceLine y={0} stroke="#374151" />
            <Legend
              iconSize={8}
              wrapperStyle={{ fontSize: 10, color: "#9ca3af" }}
            />
            <Line
              type="monotone"
              dataKey="ricci"
              stroke="#8b5cf6"
              strokeWidth={1.5}
              dot={false}
              name="Ricci R"
            />
            <Line
              type="monotone"
              dataKey="signal"
              stroke="#22c55e"
              strokeWidth={1.5}
              dot={false}
              name="signal"
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Geodesic distance timeline */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div className="text-xs text-gray-500 uppercase tracking-wider mb-3">
          Geodesic Distance to Reference States — crash (red) · rally (green)
        </div>
        <ResponsiveContainer width="100%" height={140}>
          <LineChart data={geoData} margin={{ top: 4, right: 12, left: -8, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} />
            <XAxis dataKey="cycle" tick={TICK_STYLE} />
            <YAxis domain={[0, "auto"]} tick={TICK_STYLE} />
            <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={{ color: "#9ca3af" }} />
            <Legend iconSize={8} wrapperStyle={{ fontSize: 10, color: "#9ca3af" }} />
            <Line
              type="monotone"
              dataKey="crash"
              stroke="#ef4444"
              strokeWidth={1.5}
              dot={false}
              name="Δ crash"
            />
            <Line
              type="monotone"
              dataKey="rally"
              stroke="#22c55e"
              strokeWidth={1.5}
              dot={false}
              name="Δ rally"
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Theory footnote */}
      <div className="text-xs text-gray-600 leading-relaxed border-t border-gray-800 pt-3">
        <strong className="text-gray-500">θ = (μ, σ², γ)</strong> — return distribution parameterised by mean, variance, skewness.
        Fisher Information Metric: <span className="font-mono">g_ij = E[∂_i log p · ∂_j log p]</span>.
        Ricci scalar computed via finite-difference Christoffel symbols.
        Geodesic distance is the Rao linearised arc length under g.
      </div>
    </div>
  );
}

// ── Stat card ─────────────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  sub,
  color,
}: {
  label: string;
  value: string;
  sub: string;
  color: string;
}) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-3">
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <div className="text-xl font-mono font-bold" style={{ color }}>
        {value}
      </div>
      <div className="text-xs text-gray-500 capitalize mt-0.5">{sub}</div>
    </div>
  );
}
