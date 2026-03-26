import { DollarSign, TrendingUp } from "lucide-react";

const BETS = [
  { id: "b1", market: "NYC Avg Temp > 75°F in July", side: "YES", size: "$180", entry: "52%", current: "56%", upnl: "+$14.40", status: "open" },
  { id: "b2", market: "LA Heatwave event in June", side: "YES", size: "$240", entry: "60%", current: "65%", upnl: "+$20.00", status: "open" },
  { id: "b3", market: "Seattle Temp < 50°F in October", side: "YES", size: "$200", entry: "70%", current: "73%", upnl: "+$8.57", status: "open" },
  { id: "b4", market: "Denver Snowfall > 5in November", side: "YES", size: "$120", entry: "48%", current: "51%", upnl: "+$7.06", status: "open" },
  { id: "b5", market: "Chicago Rainfall > 3in August", side: "NO", size: "$150", entry: "45%", current: "43%", upnl: "+$5.26", status: "closed", pnl: "+$37.40" },
];

export default function PolymarketBets() {
  const openBets = BETS.filter((b) => b.status === "open");
  const closedBets = BETS.filter((b) => b.status === "closed");
  const totalUpnl = openBets.reduce((s, b) => s + parseFloat(b.upnl.replace("$", "").replace("+", "")), 0);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Bets</h1>
          <p className="text-sm text-slate-500 mt-0.5">Open positions and bet history</p>
        </div>
        <div className="flex items-center gap-2 bg-emerald-500/10 border border-emerald-500/30 rounded-lg px-3 py-1.5">
          <TrendingUp size={13} className="text-emerald-400" />
          <span className="text-sm text-emerald-400 font-semibold">+${totalUpnl.toFixed(2)} unrealised</span>
        </div>
      </div>

      {/* Open positions */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
        <div className="p-4 border-b border-slate-700 flex items-center gap-2">
          <DollarSign size={14} className="text-emerald-400" />
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
            Open Positions ({openBets.length})
          </h3>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700">
              {["Market", "Side", "Size", "Entry", "Current", "Unrealised P&L"].map((h) => (
                <th key={h} className="text-left px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/60">
            {openBets.map((b) => (
              <tr key={b.id} className="hover:bg-slate-700/30 transition-colors">
                <td className="px-4 py-3 text-slate-200 text-xs">{b.market}</td>
                <td className="px-4 py-3">
                  <span className={`text-xs font-semibold px-2 py-0.5 rounded ${
                    b.side === "YES" ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400"
                  }`}>{b.side}</span>
                </td>
                <td className="px-4 py-3 text-slate-300 font-mono text-xs">{b.size}</td>
                <td className="px-4 py-3 text-slate-400 font-mono text-xs">{b.entry}</td>
                <td className="px-4 py-3 text-slate-300 font-mono text-xs">{b.current}</td>
                <td className="px-4 py-3 text-emerald-400 font-semibold font-mono text-xs">{b.upnl}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Closed */}
      {closedBets.length > 0 && (
        <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
          <div className="p-4 border-b border-slate-700 text-xs font-semibold text-slate-400 uppercase tracking-wider">
            Closed ({closedBets.length})
          </div>
          <div className="divide-y divide-slate-700/60">
            {closedBets.map((b) => (
              <div key={b.id} className="px-4 py-3 flex items-center gap-4 text-sm">
                <span className="text-slate-300 flex-1">{b.market}</span>
                <span className="text-slate-500 text-xs">{b.side}</span>
                <span className="text-slate-500 font-mono text-xs">{b.size}</span>
                <span className="text-emerald-400 font-semibold font-mono text-xs">{b.pnl}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
