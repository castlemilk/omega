import { TrendingDown, TrendingUp } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, Cell } from "recharts";

const EDGES = [
  { market: "NYC Jul Temp", edge: 9.2, signal: "temp_exceedance", confidence: 0.82 },
  { market: "LA June Heat", edge: 12.1, signal: "heat_index", confidence: 0.88 },
  { market: "Seattle Oct Temp", edge: 11.0, signal: "temp_exceedance", confidence: 0.79 },
  { market: "Denver Nov Snow", edge: 7.3, signal: "snowfall_model", confidence: 0.71 },
  { market: "Chicago Aug Rain", edge: -6.8, signal: "precipitation", confidence: 0.65 },
  { market: "Miami Q3 Hurricane", edge: -5.9, signal: "cyclone_prob", confidence: 0.58 },
];

export default function PolymarketEdges() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">Edge Detection</h1>
        <p className="text-sm text-slate-500 mt-0.5">Model probability vs market price — alpha opportunities</p>
      </div>

      <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
        <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-4">Edge by Market</h3>
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={EDGES} margin={{ top: 4, right: 4, bottom: 24, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="market" tick={{ fontSize: 10, fill: "#64748b" }} angle={-20} textAnchor="end" />
              <YAxis tick={{ fontSize: 10, fill: "#64748b" }} tickFormatter={(v) => `${v}%`} />
              <Tooltip
                contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 8 }}
                formatter={(v: number) => [`${v.toFixed(1)}%`, "Edge"]}
              />
              <ReferenceLine y={0} stroke="#475569" />
              <Bar dataKey="edge" radius={4}>
                {EDGES.map((e, i) => (
                  <Cell key={i} fill={e.edge > 0 ? "#10b981" : "#ef4444"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
        <div className="p-4 border-b border-slate-700 text-xs font-semibold text-slate-400 uppercase tracking-wider">
          Edge Opportunities
        </div>
        <div className="divide-y divide-slate-700/60">
          {EDGES.map((e) => (
            <div key={e.market} className="px-4 py-3 flex items-center gap-4">
              {e.edge > 0 ? <TrendingUp size={14} className="text-emerald-400 shrink-0" /> : <TrendingDown size={14} className="text-red-400 shrink-0" />}
              <span className="text-sm text-slate-200 flex-1">{e.market}</span>
              <span className="text-xs text-slate-500 font-mono">{e.signal}</span>
              <span className={`text-sm font-semibold font-mono ${e.edge > 0 ? "text-emerald-400" : "text-red-400"}`}>
                {e.edge > 0 ? "+" : ""}{e.edge.toFixed(1)}%
              </span>
              <span className="text-xs text-slate-500 w-20 text-right">conf {(e.confidence * 100).toFixed(0)}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
