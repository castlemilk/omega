import { useEffect, useState } from "react";
import { AlertTriangle, Database, Activity, TrendingUp, Clock } from "lucide-react";

const BASE = "";

interface DiagData {
  cycle: number;
  regime: string;
  data_freshness_seconds: number;
  active_signals: number;
  total_signals: number;
  pnl: number;
  blockers: string[];
  sit_out: boolean;
}

interface HealthCheck {
  name: string;
  status: "healthy" | "degraded" | "unhealthy" | "unknown";
  latency_ms: number;
  last_check: string;
}

export default function HealthBanner() {
  const [diag, setDiag] = useState<DiagData | null>(null);
  const [healthChecks, setHealthChecks] = useState<HealthCheck[]>([]);

  async function fetchAll() {
    try {
      const [diagRes, healthRes] = await Promise.all([
        fetch(`${BASE}/api/v1/diagnostics`),
        fetch(`${BASE}/api/v1/dashboard/health`),
      ]);
      if (diagRes.ok) {
        const d = await diagRes.json();
        if (d.available !== false) setDiag(d);
        else setDiag(null);
      }
      if (healthRes.ok) {
        setHealthChecks(await healthRes.json());
      }
    } catch {
      // silently swallow — API may not be running
    }
  }

  useEffect(() => {
    fetchAll();
    const id = setInterval(fetchAll, 5000);
    return () => clearInterval(id);
  }, []);

  // Health score 0–100 derived from health checks
  const score =
    healthChecks.length === 0
      ? null
      : Math.round(
          (healthChecks.reduce((sum, c) => {
            if (c.status === "healthy") return sum + 1;
            if (c.status === "degraded") return sum + 0.5;
            return sum;
          }, 0) /
            healthChecks.length) *
            100
        );

  const scoreColor =
    score === null
      ? "text-gray-500"
      : score >= 75
        ? "text-green-400"
        : score >= 50
          ? "text-yellow-400"
          : "text-red-400";

  const blockerCount = diag?.blockers?.length ?? 0;
  const dbCheck = healthChecks.find((c) => c.name === "postgres");
  const freshness = diag?.data_freshness_seconds;
  const isStale = freshness !== undefined && freshness > 30;
  const trainingRunning = diag !== null;
  const regime = diag?.regime;
  const regimeColor =
    regime === "bull" ? "text-green-400" : regime === "bear" ? "text-red-400" : "text-yellow-400";

  return (
    <div className="h-8 bg-surface-900 border-b border-surface-700 flex items-center px-6 gap-5 text-xs shrink-0 overflow-x-auto">
      {/* Health score */}
      <div className="flex items-center gap-1.5 shrink-0">
        <Activity size={11} className={scoreColor} />
        <span className="text-gray-500">Health</span>
        <span className={`font-mono font-semibold ${scoreColor}`}>
          {score !== null ? `${score}` : "—"}
        </span>
      </div>

      <div className="w-px h-4 bg-surface-600 shrink-0" />

      {/* Blockers badge */}
      <div className="flex items-center gap-1.5 shrink-0">
        <AlertTriangle
          size={11}
          className={blockerCount > 0 ? "text-red-400" : "text-gray-600"}
        />
        <span className="text-gray-500">Blockers</span>
        <span
          className={`font-mono font-semibold px-1.5 py-0.5 rounded text-xs ${
            blockerCount > 0 ? "bg-red-900/60 text-red-400" : "text-gray-600"
          }`}
        >
          {blockerCount}
        </span>
      </div>

      <div className="w-px h-4 bg-surface-600 shrink-0" />

      {/* Training status */}
      <div className="flex items-center gap-1.5 shrink-0">
        <TrendingUp
          size={11}
          className={trainingRunning ? "text-green-400" : "text-gray-600"}
        />
        <span className="text-gray-500">Training</span>
        <span
          className={`font-mono ${trainingRunning ? "text-green-400" : "text-gray-600"}`}
        >
          {trainingRunning ? `running · cycle #${diag?.cycle ?? "?"}` : "stopped"}
        </span>
      </div>

      {/* Data freshness */}
      {freshness !== undefined && (
        <>
          <div className="w-px h-4 bg-surface-600 shrink-0" />
          <div className="flex items-center gap-1.5 shrink-0">
            <Clock size={11} className={isStale ? "text-orange-400" : "text-gray-500"} />
            <span className="text-gray-500">Freshness</span>
            <span className={`font-mono ${isStale ? "text-orange-400" : "text-green-400"}`}>
              {freshness.toFixed(0)}s
              {isStale && " ⚠"}
            </span>
          </div>
        </>
      )}

      {/* DB status */}
      {dbCheck && (
        <>
          <div className="w-px h-4 bg-surface-600 shrink-0" />
          <div className="flex items-center gap-1.5 shrink-0">
            <Database
              size={11}
              className={
                dbCheck.status === "healthy"
                  ? "text-green-400"
                  : dbCheck.status === "degraded"
                    ? "text-yellow-400"
                    : "text-red-400"
              }
            />
            <span className="text-gray-500">DB</span>
            <span
              className={`font-mono font-semibold uppercase ${
                dbCheck.status === "healthy"
                  ? "text-green-400"
                  : dbCheck.status === "degraded"
                    ? "text-yellow-400"
                    : "text-red-400"
              }`}
            >
              {dbCheck.status}
            </span>
          </div>
        </>
      )}

      {/* Regime */}
      {regime && (
        <>
          <div className="w-px h-4 bg-surface-600 shrink-0" />
          <div className="flex items-center gap-1.5 shrink-0">
            <span className="text-gray-500">Regime</span>
            <span className={`font-mono font-semibold uppercase ${regimeColor}`}>{regime}</span>
          </div>
        </>
      )}

      {/* Signals active — pushed to right */}
      {diag?.active_signals !== undefined && (
        <div className="flex items-center gap-1.5 ml-auto shrink-0">
          <span className="text-gray-500">Signals</span>
          <span className="font-mono text-gray-300">
            {diag.active_signals}/{diag.total_signals}
          </span>
        </div>
      )}
    </div>
  );
}
