import { useEffect, useState } from "react";
import { Cloud, TrendingDown, Droplets, DollarSign, Activity } from "lucide-react";

interface MarketStat {
  label: string;
  value: string;
  sub?: string;
  color?: string;
}

const MOCK_STATS: MarketStat[] = [
  { label: "Active Markets", value: "24", sub: "weather prediction" },
  { label: "Open Edges", value: "7", sub: "avg edge 9.2%", color: "text-emerald-400" },
  { label: "Deployed Capital", value: "$1,240", sub: "Kelly-sized positions" },
  { label: "Realised P&L", value: "+$87.40", sub: "last 30 days", color: "text-emerald-400" },
];

const MOCK_MARKETS = [
  { id: "m1", title: "NYC Avg Temp > 75°F in July", modelProb: 0.61, mktProb: 0.52, edge: 0.09, status: "open" },
  { id: "m2", title: "Chicago Rainfall > 3in in August", modelProb: 0.38, mktProb: 0.45, edge: -0.07, status: "skip" },
  { id: "m3", title: "LA Heatwave event in June", modelProb: 0.72, mktProb: 0.60, edge: 0.12, status: "open" },
  { id: "m4", title: "Miami Hurricane Category 1+ Q3", modelProb: 0.29, mktProb: 0.35, edge: -0.06, status: "skip" },
  { id: "m5", title: "Seattle Temp < 50°F in October", modelProb: 0.81, mktProb: 0.70, edge: 0.11, status: "open" },
];

export default function PolymarketOverview() {
  const [ts, setTs] = useState(new Date().toLocaleTimeString());
  useEffect(() => {
    const id = setInterval(() => setTs(new Date().toLocaleTimeString()), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Polymarket Overview</h1>
          <p className="text-sm text-slate-500 mt-0.5">Weather prediction market intelligence</p>
        </div>
        <span className="text-xs text-slate-500 font-mono">{ts}</span>
      </div>

      {/* Stats strip */}
      <div className="grid grid-cols-4 gap-3">
        {MOCK_STATS.map((s) => (
          <div key={s.label} className="bg-slate-800 rounded-xl border border-slate-700 p-4">
            <p className="text-xs text-slate-500 mb-1">{s.label}</p>
            <p className={`text-2xl font-bold ${s.color ?? "text-slate-100"}`}>{s.value}</p>
            {s.sub && <p className="text-xs text-slate-500 mt-0.5">{s.sub}</p>}
          </div>
        ))}
      </div>

      {/* Pipeline steps */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
        <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-4">
          Pipeline
        </h3>
        <div className="flex items-center gap-2 overflow-x-auto">
          {[
            { icon: Droplets, label: "WeatherData", desc: "GEFS ensemble" },
            { icon: Activity, label: "MarketPricing", desc: "Gamma API" },
            { icon: TrendingDown, label: "EdgeDetection", desc: "Model vs mkt" },
            { icon: DollarSign, label: "RiskCheck", desc: "Kelly sizing" },
          ].map((step, i, arr) => (
            <div key={step.label} className="flex items-center gap-2 shrink-0">
              <div className="flex flex-col items-center gap-1 bg-slate-900 border border-slate-700 rounded-lg px-4 py-3 min-w-[110px]">
                <step.icon size={16} className="text-blue-400" />
                <span className="text-xs font-medium text-slate-300">{step.label}</span>
                <span className="text-[10px] text-slate-500">{step.desc}</span>
              </div>
              {i < arr.length - 1 && <span className="text-slate-600">→</span>}
            </div>
          ))}
        </div>
      </div>

      {/* Market table */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
        <div className="p-4 border-b border-slate-700 flex items-center gap-2">
          <Cloud size={14} className="text-blue-400" />
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
            Top Markets
          </h3>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700">
              {["Market", "Model Prob", "Market Prob", "Edge", "Action"].map((h) => (
                <th
                  key={h}
                  className="text-left px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wider"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/60">
            {MOCK_MARKETS.map((m) => (
              <tr key={m.id} className="hover:bg-slate-700/30 transition-colors">
                <td className="px-4 py-3 text-slate-200 text-xs max-w-xs truncate">{m.title}</td>
                <td className="px-4 py-3 text-slate-300 font-mono text-xs">
                  {(m.modelProb * 100).toFixed(0)}%
                </td>
                <td className="px-4 py-3 text-slate-300 font-mono text-xs">
                  {(m.mktProb * 100).toFixed(0)}%
                </td>
                <td
                  className={`px-4 py-3 font-mono font-semibold text-xs ${
                    m.edge > 0 ? "text-emerald-400" : "text-red-400"
                  }`}
                >
                  {m.edge > 0 ? "+" : ""}
                  {(m.edge * 100).toFixed(1)}%
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
                      m.status === "open"
                        ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                        : "bg-slate-700 text-slate-500"
                    }`}
                  >
                    {m.status === "open" ? "BET" : "SKIP"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
