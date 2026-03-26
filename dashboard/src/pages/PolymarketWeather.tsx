import { Droplets, Wind, Thermometer } from "lucide-react";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

const FORECAST = Array.from({ length: 14 }, (_, i) => ({
  day: `+${i + 1}d`,
  tempHigh: 72 + Math.sin(i / 3) * 8 + Math.random() * 4,
  tempLow: 58 + Math.sin(i / 3) * 6 + Math.random() * 3,
  precip: Math.max(0, Math.sin(i / 2) * 0.4 + Math.random() * 0.2),
}));

const ENSEMBLES = [
  { member: "GFS", prob: 0.61, bias: "+1.2°F" },
  { member: "ECMWF", prob: 0.64, bias: "+0.8°F" },
  { member: "CFS", prob: 0.58, bias: "+1.5°F" },
  { member: "NAM", prob: 0.59, bias: "+1.0°F" },
  { member: "Ensemble Mean", prob: 0.61, bias: "+1.1°F" },
];

export default function PolymarketWeather() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">Weather Ensemble</h1>
        <p className="text-sm text-slate-500 mt-0.5">GEFS probabilistic forecasts powering prediction market models</p>
      </div>

      <div className="grid grid-cols-3 gap-3">
        {[
          { icon: Thermometer, label: "Temp Exceedance", value: "61%", sub: "NYC > 75°F in July", color: "text-orange-400" },
          { icon: Droplets, label: "Precipitation", value: "38%", sub: "Chicago > 3in Aug", color: "text-blue-400" },
          { icon: Wind, label: "Ensemble Spread", value: "±3.2°F", sub: "model uncertainty", color: "text-slate-300" },
        ].map((s) => (
          <div key={s.label} className="bg-slate-800 rounded-xl border border-slate-700 p-4">
            <div className="flex items-center gap-2 mb-2">
              <s.icon size={14} className={s.color} />
              <span className="text-xs text-slate-500">{s.label}</span>
            </div>
            <p className={`text-2xl font-bold ${s.color}`}>{s.value}</p>
            <p className="text-xs text-slate-600 mt-0.5">{s.sub}</p>
          </div>
        ))}
      </div>

      <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
        <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-4">14-Day Temperature Forecast</h3>
        <div className="h-48">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={FORECAST}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="day" tick={{ fontSize: 10, fill: "#64748b" }} />
              <YAxis tick={{ fontSize: 10, fill: "#64748b" }} tickFormatter={(v) => `${v.toFixed(0)}°F`} />
              <Tooltip contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 8 }} />
              <Area type="monotone" dataKey="tempHigh" stroke="#f97316" fill="#f9731622" strokeWidth={2} name="High" />
              <Area type="monotone" dataKey="tempLow" stroke="#60a5fa" fill="#60a5fa22" strokeWidth={2} name="Low" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
        <div className="p-4 border-b border-slate-700 text-xs font-semibold text-slate-400 uppercase tracking-wider">
          Ensemble Members — NYC July Temperature
        </div>
        <div className="divide-y divide-slate-700/60">
          {ENSEMBLES.map((e) => (
            <div key={e.member} className="px-4 py-3 flex items-center gap-4">
              <span className={`text-sm ${e.member === "Ensemble Mean" ? "text-slate-100 font-semibold" : "text-slate-300"} flex-1`}>{e.member}</span>
              <div className="w-40 bg-slate-700 rounded-full h-1.5">
                <div className="bg-blue-400 h-1.5 rounded-full" style={{ width: `${e.prob * 100}%` }} />
              </div>
              <span className="text-sm font-mono text-blue-400 w-12 text-right">{(e.prob * 100).toFixed(0)}%</span>
              <span className="text-xs text-slate-500 w-16 text-right">{e.bias}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
