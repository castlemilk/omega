// TRADE ANALYSIS — winner vs loser comparison: signal profiles, predictiveness ranking, regime breakdown
import { useEffect, useState, useCallback } from "react";
import {
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ScatterChart,
  Scatter,
  ReferenceLine,
} from "recharts";
import {
  TrendingUp,
  TrendingDown,
  RefreshCw,
  BarChart2,
  Award,
  AlertCircle,
} from "lucide-react";
import { fetchTrades } from "../api/victoria";

const TOOLTIP_STYLE = {
  background: "#1f2937",
  border: "1px solid #374151",
  borderRadius: 6,
  fontSize: 11,
};
const TICK_STYLE = { fontSize: 10, fill: "#6b7280" };

// ── Types ──────────────────────────────────────────────────────────────────────

interface Trade {
  ts: string;
  sym: string;
  side: "LONG" | "SHORT";
  size: number;
  entry: number;
  exit: number;
  pnl: number;
  slippage: number;
  duration: string;
  regime?: string;
}

interface SignalProfile {
  signal: string;
  winnerAvg: number;
  loserAvg: number;
  correlation: number; // +1 = predicts wins, -1 = predicts losses
}

interface RegimeStat {
  regime: string;
  trades: number;
  winRate: number;
  avgPnl: number;
  totalPnl: number;
}

// ── Mock data ──────────────────────────────────────────────────────────────────

function buildMockTrades(): Trade[] {
  const symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT"];
  const regimes = ["BULL", "SIDEWAYS", "BEAR"];
  const regimeWeights = [0.5, 0.35, 0.15]; // probability distribution
  const seed = 42;

  // Seeded pseudo-random (same output every render)
  let r = seed;
  const rand = () => {
    r = (r * 1664525 + 1013904223) & 0xffffffff;
    return (r >>> 0) / 0xffffffff;
  };

  const trades: Trade[] = [];
  for (let i = 0; i < 40; i++) {
    const sym = symbols[Math.floor(rand() * 3)];
    const side = rand() > 0.5 ? "LONG" : ("SHORT" as const);
    const regimeRoll = rand();
    const regime =
      regimeRoll < regimeWeights[0]
        ? regimes[0]
        : regimeRoll < regimeWeights[0] + regimeWeights[1]
        ? regimes[1]
        : regimes[2];

    // Winners more likely in BULL, losers more likely in BEAR
    const winBias =
      regime === "BULL" ? 0.65 : regime === "SIDEWAYS" ? 0.5 : 0.35;
    const isWinner = rand() < winBias;

    const entry =
      sym === "BTC/USDT" ? 60000 + rand() * 10000 : sym === "ETH/USDT" ? 3000 + rand() * 800 : 130 + rand() * 50;
    const size = 0.1 + rand() * 0.8;
    const pctMove = isWinner ? 0.005 + rand() * 0.035 : -(0.003 + rand() * 0.025);
    const exit = entry * (1 + (side === "LONG" ? pctMove : -pctMove));
    const pnl = (exit - entry) * size * (side === "LONG" ? 1 : -1);

    const daysAgo = Math.floor(rand() * 30);
    const ts = new Date(Date.now() - daysAgo * 86400000).toISOString().slice(0, 16).replace("T", " ");
    const durationHours = 1 + Math.floor(rand() * 24);

    trades.push({
      ts,
      sym,
      side,
      size: +size.toFixed(3),
      entry: +entry.toFixed(2),
      exit: +exit.toFixed(2),
      pnl: +pnl.toFixed(2),
      slippage: +(rand() * 0.02).toFixed(4),
      duration: `${durationHours}h ${Math.floor(rand() * 59)}m`,
      regime,
    });
  }
  return trades.sort((a, b) => b.ts.localeCompare(a.ts));
}

const MOCK_TRADES = buildMockTrades();

const MOCK_SIGNAL_PROFILES: SignalProfile[] = [
  { signal: "ORDERFLOW",   winnerAvg: 0.71, loserAvg: 0.18, correlation: 0.82 },
  { signal: "MOMENTUM",    winnerAvg: 0.58, loserAvg: -0.22, correlation: 0.74 },
  { signal: "SENTIMENT",   winnerAvg: 0.44, loserAvg: 0.21, correlation: 0.41 },
  { signal: "REGIME",      winnerAvg: 0.62, loserAvg: 0.38, correlation: 0.35 },
  { signal: "VOLUME",      winnerAvg: 0.39, loserAvg: 0.41, correlation: -0.03 },
  { signal: "SMART_MONEY", winnerAvg: 0.55, loserAvg: 0.14, correlation: 0.69 },
  { signal: "MACRO",       winnerAvg: 0.31, loserAvg: 0.28, correlation: 0.12 },
  { signal: "DERIVATIVES", winnerAvg: 0.48, loserAvg: -0.08, correlation: 0.55 },
];

// ── Helpers ────────────────────────────────────────────────────────────────────

function computeRegimeStats(trades: Trade[]): RegimeStat[] {
  const byRegime: Record<string, Trade[]> = {};
  for (const t of trades) {
    const r = t.regime ?? "UNKNOWN";
    if (!byRegime[r]) byRegime[r] = [];
    byRegime[r].push(t);
  }
  return Object.entries(byRegime).map(([regime, ts]) => ({
    regime,
    trades: ts.length,
    winRate: +(ts.filter((t) => t.pnl > 0).length / ts.length).toFixed(3),
    avgPnl: +(ts.reduce((s, t) => s + t.pnl, 0) / ts.length).toFixed(2),
    totalPnl: +ts.reduce((s, t) => s + t.pnl, 0).toFixed(2),
  }));
}

function pnlColor(v: number): string {
  return v > 0 ? "#22c55e" : v < 0 ? "#ef4444" : "#6b7280";
}

function correlationColor(v: number): string {
  if (v > 0.5) return "#22c55e";
  if (v > 0.2) return "#86efac";
  if (v < -0.2) return "#fca5a5";
  if (v < -0.5) return "#ef4444";
  return "#6b7280";
}

// ── Signal profile comparison chart ────────────────────────────────────────────

function SignalProfileChart({ profiles }: { profiles: SignalProfile[] }) {
  const data = profiles.map((p) => ({
    name: p.signal.replace(/_/g, " "),
    winners: +p.winnerAvg.toFixed(3),
    losers: +p.loserAvg.toFixed(3),
  }));

  return (
    <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">
        Avg Signal Value — Winners vs Losers
      </p>
      <p className="text-xs text-gray-600 mb-3">
        How each signal fires differently before winning vs losing trades
      </p>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis dataKey="name" tick={{ ...TICK_STYLE, fontSize: 9 }} />
          <YAxis domain={[-0.4, 1.0]} tick={TICK_STYLE} width={32} />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Legend wrapperStyle={{ fontSize: 10, color: "#9ca3af" }} />
          <ReferenceLine y={0} stroke="#374151" />
          <Bar dataKey="winners" name="Winners" fill="#22c55e" fillOpacity={0.8} radius={[2, 2, 0, 0]} />
          <Bar dataKey="losers" name="Losers" fill="#ef4444" fillOpacity={0.8} radius={[2, 2, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Signal predictiveness ranking ──────────────────────────────────────────────

function PredictiveSignalsChart({ profiles }: { profiles: SignalProfile[] }) {
  const sorted = [...profiles].sort((a, b) => Math.abs(b.correlation) - Math.abs(a.correlation));
  const data = sorted.map((p) => ({
    name: p.signal.replace(/_/g, " "),
    correlation: +p.correlation.toFixed(3),
  }));

  return (
    <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">
        Signal Predictiveness (Win Correlation)
      </p>
      <p className="text-xs text-gray-600 mb-3">
        Pearson correlation between signal value and trade outcome
      </p>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, left: 64, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis type="number" domain={[-1, 1]} tick={TICK_STYLE} />
          <YAxis type="category" dataKey="name" tick={TICK_STYLE} width={60} />
          <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: number) => [v.toFixed(3), "Correlation"]} />
          <ReferenceLine x={0} stroke="#374151" />
          <Bar dataKey="correlation" radius={[0, 3, 3, 0]}>
            {data.map((d, i) => (
              <Cell key={i} fill={correlationColor(d.correlation)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Regime breakdown ───────────────────────────────────────────────────────────

function RegimeBreakdown({ trades }: { trades: Trade[] }) {
  const stats = computeRegimeStats(trades);
  const REGIME_COLOR: Record<string, string> = {
    BULL: "#22c55e",
    SIDEWAYS: "#eab308",
    BEAR: "#ef4444",
    UNKNOWN: "#6b7280",
  };

  return (
    <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
        Performance by Regime
      </p>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-500 border-b border-gray-700">
            <th className="text-left pb-2 font-medium">Regime</th>
            <th className="text-right pb-2 font-medium">Trades</th>
            <th className="text-right pb-2 font-medium">Win Rate</th>
            <th className="text-right pb-2 font-medium">Avg PnL</th>
            <th className="text-right pb-2 font-medium">Total PnL</th>
          </tr>
        </thead>
        <tbody>
          {stats.map((s) => (
            <tr key={s.regime} className="border-b border-gray-700/50 hover:bg-gray-700/20">
              <td className="py-2">
                <span
                  className="px-2 py-0.5 rounded text-xs font-semibold"
                  style={{
                    backgroundColor: REGIME_COLOR[s.regime] + "20",
                    color: REGIME_COLOR[s.regime],
                    border: `1px solid ${REGIME_COLOR[s.regime]}50`,
                  }}
                >
                  {s.regime}
                </span>
              </td>
              <td className="text-right py-2 font-mono text-gray-300">{s.trades}</td>
              <td className="text-right py-2 font-mono" style={{ color: s.winRate >= 0.5 ? "#22c55e" : "#ef4444" }}>
                {(s.winRate * 100).toFixed(0)}%
              </td>
              <td className="text-right py-2 font-mono" style={{ color: pnlColor(s.avgPnl) }}>
                {s.avgPnl >= 0 ? "+" : ""}${s.avgPnl.toFixed(0)}
              </td>
              <td className="text-right py-2 font-mono" style={{ color: pnlColor(s.totalPnl) }}>
                {s.totalPnl >= 0 ? "+" : ""}${s.totalPnl.toFixed(0)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── PnL scatter chart ──────────────────────────────────────────────────────────

function PnlScatterChart({ trades }: { trades: Trade[] }) {
  const data = trades.map((t, i) => ({
    x: i,
    y: t.pnl,
    sym: t.sym.replace("/USDT", ""),
    regime: t.regime,
  }));

  return (
    <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
        PnL Distribution
      </p>
      <ResponsiveContainer width="100%" height={140}>
        <ScatterChart margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis dataKey="x" tick={false} label={{ value: "Trade #", fontSize: 9, fill: "#6b7280" }} />
          <YAxis dataKey="y" tick={TICK_STYLE} width={40} />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            formatter={(v: number, _name: string, props: { payload?: { sym?: string; regime?: string } }) => [
              `$${v.toFixed(2)}`,
              `${props.payload?.sym ?? ""} (${props.payload?.regime ?? ""})`,
            ]}
          />
          <ReferenceLine y={0} stroke="#374151" strokeDasharray="4 2" />
          <Scatter data={data} fill="#6366f1">
            {data.map((d, i) => (
              <Cell key={i} fill={d.y > 0 ? "#22c55e" : "#ef4444"} fillOpacity={0.8} />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Trade table ────────────────────────────────────────────────────────────────

function TradeTable({ trades }: { trades: Trade[] }) {
  return (
    <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
        Trade Log ({trades.length})
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-500 border-b border-gray-700">
              {["Time", "Symbol", "Side", "Size", "Entry", "Exit", "PnL", "Regime", "Duration"].map(
                (h) => (
                  <th key={h} className="text-right first:text-left pb-2 font-medium pr-3 last:pr-0">
                    {h}
                  </th>
                )
              )}
            </tr>
          </thead>
          <tbody>
            {trades.slice(0, 20).map((t, i) => (
              <tr key={i} className="border-b border-gray-700/40 hover:bg-gray-700/20">
                <td className="py-1.5 pr-3 font-mono text-gray-500">{t.ts.slice(5, 16)}</td>
                <td className="py-1.5 pr-3 text-right font-mono text-gray-300">
                  {t.sym.replace("/USDT", "")}
                </td>
                <td className="py-1.5 pr-3 text-right">
                  <span
                    className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                      t.side === "LONG"
                        ? "bg-emerald-900/50 text-emerald-400"
                        : "bg-red-900/50 text-red-400"
                    }`}
                  >
                    {t.side}
                  </span>
                </td>
                <td className="py-1.5 pr-3 text-right font-mono text-gray-400">{t.size.toFixed(3)}</td>
                <td className="py-1.5 pr-3 text-right font-mono text-gray-400">
                  {t.entry.toLocaleString()}
                </td>
                <td className="py-1.5 pr-3 text-right font-mono text-gray-400">
                  {t.exit.toLocaleString()}
                </td>
                <td
                  className="py-1.5 pr-3 text-right font-mono font-semibold"
                  style={{ color: pnlColor(t.pnl) }}
                >
                  {t.pnl >= 0 ? "+" : ""}${t.pnl.toFixed(2)}
                </td>
                <td className="py-1.5 pr-3 text-right">
                  <span className="text-gray-500">{t.regime ?? "—"}</span>
                </td>
                <td className="py-1.5 text-right font-mono text-gray-500">{t.duration}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {trades.length > 20 && (
          <p className="text-xs text-gray-600 mt-2 text-center">
            Showing 20 of {trades.length} trades
          </p>
        )}
      </div>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function TradeAnalysis() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [signalProfiles, setSignalProfiles] = useState<SignalProfile[]>([]);
  const [loading, setLoading] = useState(false);
  const [fromMock, setFromMock] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);

    // Try victoria API, fall back to mock
    try {
      const tradesResult = await fetchTrades();

      if (!tradesResult.fromMock && tradesResult.trades.length > 0) {
        const mapped: Trade[] = tradesResult.trades.map((t) => ({
          ts: t.ts,
          sym: t.sym,
          side: t.side as "LONG" | "SHORT",
          size: t.size,
          entry: t.entry,
          exit: t.exit,
          pnl: t.pnl,
          slippage: t.slippage,
          duration: t.duration,
        }));
        setTrades(mapped);
        setFromMock(false);
      } else {
        setTrades(MOCK_TRADES);
        setFromMock(true);
      }

      // Signal profiles require winner/loser correlation with decision snapshots
      // Fall back to mock profiles until that join is available from the API
      setSignalProfiles(MOCK_SIGNAL_PROFILES);
    } catch {
      setTrades(MOCK_TRADES);
      setSignalProfiles(MOCK_SIGNAL_PROFILES);
      setFromMock(true);
    }

    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const winners = trades.filter((t) => t.pnl > 0);
  const losers = trades.filter((t) => t.pnl < 0);
  const totalPnl = trades.reduce((s, t) => s + t.pnl, 0);
  const winRate = trades.length > 0 ? winners.length / trades.length : 0;
  const avgWinner = winners.length > 0 ? winners.reduce((s, t) => s + t.pnl, 0) / winners.length : 0;
  const avgLoser = losers.length > 0 ? losers.reduce((s, t) => s + t.pnl, 0) / losers.length : 0;

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <BarChart2 className="w-5 h-5 text-indigo-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Trade Analysis</h1>
            <p className="text-xs text-gray-500 mt-0.5">
              Winner vs loser comparison — signal predictiveness, regime breakdown
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {fromMock && (
            <span className="text-xs px-2 py-1 bg-blue-900/40 text-blue-300 border border-blue-800 rounded">
              mock data
            </span>
          )}
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

      {/* Summary stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: "Total Trades", value: trades.length, color: "text-white" },
          {
            label: "Win Rate",
            value: `${(winRate * 100).toFixed(1)}%`,
            color: winRate >= 0.5 ? "text-green-400" : "text-red-400",
          },
          {
            label: "Avg Winner",
            value: `+$${avgWinner.toFixed(0)}`,
            color: "text-green-400",
          },
          {
            label: "Avg Loser",
            value: `-$${Math.abs(avgLoser).toFixed(0)}`,
            color: "text-red-400",
          },
        ].map((s) => (
          <div key={s.label} className="bg-gray-800 rounded-xl border border-gray-700 px-4 py-3">
            <p className={`text-2xl font-bold ${s.color}`}>{s.value}</p>
            <p className="text-xs text-gray-500 mt-0.5">{s.label}</p>
          </div>
        ))}
      </div>

      {/* Winner/loser breakdown bar */}
      <div className="bg-gray-800 rounded-xl border border-gray-700 px-4 py-3 flex items-center gap-6">
        <div className="flex items-center gap-2">
          <TrendingUp className="w-4 h-4 text-green-400" />
          <span className="text-sm font-semibold text-green-400">{winners.length} winners</span>
          <span className="text-xs text-gray-500">
            +${winners.reduce((s, t) => s + t.pnl, 0).toFixed(0)} total
          </span>
        </div>
        <div className="flex-1 h-2 bg-gray-700 rounded-full overflow-hidden">
          <div
            className="h-full bg-green-500 rounded-full"
            style={{ width: `${(winners.length / Math.max(trades.length, 1)) * 100}%` }}
          />
        </div>
        <div className="flex items-center gap-2">
          <TrendingDown className="w-4 h-4 text-red-400" />
          <span className="text-sm font-semibold text-red-400">{losers.length} losers</span>
          <span className="text-xs text-gray-500">
            ${losers.reduce((s, t) => s + t.pnl, 0).toFixed(0)} total
          </span>
        </div>
        <div className="text-right shrink-0">
          <span className="text-sm font-bold" style={{ color: pnlColor(totalPnl) }}>
            {totalPnl >= 0 ? "+" : ""}${totalPnl.toFixed(0)} net
          </span>
        </div>
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <SignalProfileChart profiles={signalProfiles} />
        <PredictiveSignalsChart profiles={signalProfiles} />
      </div>

      {/* PnL scatter */}
      <PnlScatterChart trades={trades} />

      {/* Regime breakdown */}
      <RegimeBreakdown trades={trades} />

      {/* Top winners / top losers side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-gray-800 rounded-xl border border-green-900/50 p-4">
          <div className="flex items-center gap-2 mb-3">
            <Award className="w-4 h-4 text-green-400" />
            <p className="text-xs font-semibold text-green-400 uppercase tracking-wide">
              Top Winners
            </p>
          </div>
          <div className="space-y-2">
            {winners
              .sort((a, b) => b.pnl - a.pnl)
              .slice(0, 5)
              .map((t, i) => (
                <div key={i} className="flex items-center justify-between text-xs">
                  <span className="font-mono text-gray-400">{t.sym.replace("/USDT", "")}</span>
                  <span className="text-gray-500">{t.side}</span>
                  <span className="text-gray-500">{t.regime}</span>
                  <span className="font-mono font-semibold text-green-400">
                    +${t.pnl.toFixed(2)}
                  </span>
                </div>
              ))}
          </div>
        </div>
        <div className="bg-gray-800 rounded-xl border border-red-900/50 p-4">
          <div className="flex items-center gap-2 mb-3">
            <AlertCircle className="w-4 h-4 text-red-400" />
            <p className="text-xs font-semibold text-red-400 uppercase tracking-wide">
              Top Losers
            </p>
          </div>
          <div className="space-y-2">
            {losers
              .sort((a, b) => a.pnl - b.pnl)
              .slice(0, 5)
              .map((t, i) => (
                <div key={i} className="flex items-center justify-between text-xs">
                  <span className="font-mono text-gray-400">{t.sym.replace("/USDT", "")}</span>
                  <span className="text-gray-500">{t.side}</span>
                  <span className="text-gray-500">{t.regime}</span>
                  <span className="font-mono font-semibold text-red-400">
                    ${t.pnl.toFixed(2)}
                  </span>
                </div>
              ))}
          </div>
        </div>
      </div>

      {/* Full trade table */}
      <TradeTable trades={trades} />
    </div>
  );
}
