import { Cloud, ExternalLink } from "lucide-react";

const MARKETS = [
  { id: "m1", title: "NYC Avg Temp > 75°F in July 2026", volume: "$24,100", liquidity: "$8,200", modelProb: 0.61, mktProb: 0.52, edge: 0.09, expires: "Jul 31" },
  { id: "m2", title: "Chicago Rainfall > 3in in August 2026", volume: "$11,400", liquidity: "$3,800", modelProb: 0.38, mktProb: 0.45, edge: -0.07, expires: "Aug 31" },
  { id: "m3", title: "LA Heatwave event in June 2026", volume: "$18,700", liquidity: "$6,400", modelProb: 0.72, mktProb: 0.60, edge: 0.12, expires: "Jun 30" },
  { id: "m4", title: "Miami Hurricane Category 1+ Q3 2026", volume: "$9,200", liquidity: "$2,900", modelProb: 0.29, mktProb: 0.35, edge: -0.06, expires: "Sep 30" },
  { id: "m5", title: "Seattle Temp < 50°F in October 2026", volume: "$7,600", liquidity: "$2,200", modelProb: 0.81, mktProb: 0.70, edge: 0.11, expires: "Oct 31" },
  { id: "m6", title: "Denver Snowfall > 5in in November 2026", volume: "$5,300", liquidity: "$1,800", modelProb: 0.55, mktProb: 0.48, edge: 0.07, expires: "Nov 30" },
];

export default function PolymarketMarkets() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Markets</h1>
          <p className="text-sm text-slate-500 mt-0.5">Live Polymarket weather prediction markets</p>
        </div>
        <span className="text-xs text-slate-500">{MARKETS.length} markets tracked</span>
      </div>

      <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
        <div className="p-4 border-b border-slate-700 flex items-center gap-2">
          <Cloud size={14} className="text-blue-400" />
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
            Weather Markets
          </h3>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700">
              {["Market", "Volume", "Liquidity", "Model", "Market", "Edge", "Expires"].map((h) => (
                <th key={h} className="text-left px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/60">
            {MARKETS.map((m) => (
              <tr key={m.id} className="hover:bg-slate-700/30 transition-colors">
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className="text-slate-200 text-xs">{m.title}</span>
                    <ExternalLink size={10} className="text-slate-600 shrink-0" />
                  </div>
                </td>
                <td className="px-4 py-3 text-slate-400 font-mono text-xs">{m.volume}</td>
                <td className="px-4 py-3 text-slate-400 font-mono text-xs">{m.liquidity}</td>
                <td className="px-4 py-3 text-blue-400 font-mono text-xs">{(m.modelProb * 100).toFixed(0)}%</td>
                <td className="px-4 py-3 text-slate-300 font-mono text-xs">{(m.mktProb * 100).toFixed(0)}%</td>
                <td className={`px-4 py-3 font-mono font-semibold text-xs ${m.edge > 0 ? "text-emerald-400" : "text-red-400"}`}>
                  {m.edge > 0 ? "+" : ""}{(m.edge * 100).toFixed(1)}%
                </td>
                <td className="px-4 py-3 text-slate-500 text-xs">{m.expires}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
