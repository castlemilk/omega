import { useEffect, useState } from "react";
import { client } from "../client";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  AreaChart,
  Area,
  ComposedChart,
  ResponsiveContainer,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
} from "recharts";
import type { Node } from "../gen/omega/v1/types_pb";

// ---------------------------------------------------------------------------
// Shared chart theme
// ---------------------------------------------------------------------------
const TOOLTIP_STYLE = {
  background: "#1f2937",
  border: "1px solid #374151",
  borderRadius: 6,
  fontSize: 11,
};
const GRID_COLOR = "#374151";
const TICK_STYLE = { fontSize: 10, fill: "#6b7280" };

// ---------------------------------------------------------------------------
// Empty-state placeholder chart (shows axes + "No data yet" watermark)
// ---------------------------------------------------------------------------
function EmptyChart({ label }: { label: string }) {
  return (
    <div className="h-32 flex items-center justify-center text-gray-600 text-xs font-mono border border-dashed border-gray-700 rounded-lg">
      {label}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section wrapper
// ---------------------------------------------------------------------------
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest mb-3">
        {title}
      </h2>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Per-node latency card (existing behaviour preserved)
// ---------------------------------------------------------------------------
function NodeLatencyCard({ node, history }: { node: Node; history: { ms: number }[] }) {
  return (
    <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm font-medium text-white">{node.name}</p>
        <span className="text-xs text-gray-500">p95: {node.p95LatencyMs.toFixed(0)}ms</span>
      </div>
      {history.length > 1 ? (
        <div className="h-32">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={history}>
              <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} />
              <XAxis hide />
              <YAxis width={35} tick={TICK_STYLE} />
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                formatter={(v: number) => [`${v.toFixed(0)}ms`]}
              />
              <Line
                type="monotone"
                dataKey="ms"
                name="latency"
                stroke="#6366f1"
                dot={false}
                strokeWidth={1.5}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <EmptyChart label="No latency history" />
      )}
      <div className="flex gap-4 mt-3 text-xs text-gray-500">
        <span>err: {(node.errorRate * 100).toFixed(1)}%</span>
        <span>avg: {node.avgLatencyMs.toFixed(0)}ms</span>
        <span>total: {String(node.executionsTotal)} execs</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Error rate bar chart across all nodes
// ---------------------------------------------------------------------------
function ErrorRateChart({ nodes }: { nodes: Node[] }) {
  if (nodes.length === 0) return <EmptyChart label="No nodes — error rate data unavailable" />;

  const data = nodes.map((n) => ({
    name: n.name.length > 12 ? n.name.slice(0, 12) + "…" : n.name,
    errorPct: parseFloat((n.errorRate * 100).toFixed(2)),
  }));

  return (
    <div className="h-40">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 8, bottom: 24, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} vertical={false} />
          <XAxis
            dataKey="name"
            tick={{ ...TICK_STYLE, fontSize: 9 }}
            angle={-25}
            textAnchor="end"
          />
          <YAxis width={32} tick={TICK_STYLE} unit="%" domain={[0, "auto"]} />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            formatter={(v: number) => [`${v.toFixed(2)}%`, "error rate"]}
          />
          <ReferenceLine y={5} stroke="#ef4444" strokeDasharray="4 2" strokeWidth={1} />
          <Bar dataKey="errorPct" name="error rate" fill="#f59e0b" radius={[2, 2, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Cycle throughput area chart (placeholder with live-cycle counter context)
// ---------------------------------------------------------------------------
function CycleThroughputChart({ nodes }: { nodes: Node[] }) {
  // Derive total executions per node as a proxy for throughput
  if (nodes.length === 0) return <EmptyChart label="No cycle data yet — run the orchestrator" />;

  const data = nodes.map((n) => ({
    name: n.name.length > 12 ? n.name.slice(0, 12) + "…" : n.name,
    execs: Number(n.executionsTotal),
    avgMs: parseFloat(n.avgLatencyMs.toFixed(1)),
  }));

  return (
    <div className="h-44">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 4, right: 8, bottom: 28, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} />
          <XAxis
            dataKey="name"
            tick={{ ...TICK_STYLE, fontSize: 9 }}
            angle={-25}
            textAnchor="end"
          />
          <YAxis
            yAxisId="left"
            width={40}
            tick={TICK_STYLE}
            label={{
              value: "execs",
              angle: -90,
              position: "insideLeft",
              fill: "#6b7280",
              fontSize: 9,
            }}
          />
          <YAxis yAxisId="right" orientation="right" width={40} tick={TICK_STYLE} unit="ms" />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Legend wrapperStyle={{ fontSize: 10 }} />
          <Bar
            yAxisId="left"
            dataKey="execs"
            name="executions"
            fill="#6366f1"
            radius={[2, 2, 0, 0]}
            opacity={0.8}
          />
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="avgMs"
            name="avg latency"
            stroke="#10b981"
            dot={false}
            strokeWidth={1.5}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

// ---------------------------------------------------------------------------
// P95 latency comparison across nodes
// ---------------------------------------------------------------------------
function P95ComparisonChart({ nodes }: { nodes: Node[] }) {
  if (nodes.length === 0) return <EmptyChart label="No p95 data available" />;

  const data = nodes.map((n) => ({
    name: n.name.length > 14 ? n.name.slice(0, 14) + "…" : n.name,
    p95: parseFloat(n.p95LatencyMs.toFixed(1)),
    avg: parseFloat(n.avgLatencyMs.toFixed(1)),
  }));

  return (
    <div className="h-44">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 8, bottom: 28, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} vertical={false} />
          <XAxis
            dataKey="name"
            tick={{ ...TICK_STYLE, fontSize: 9 }}
            angle={-25}
            textAnchor="end"
          />
          <YAxis width={40} tick={TICK_STYLE} unit="ms" />
          <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: number) => [`${v.toFixed(1)}ms`]} />
          <Legend wrapperStyle={{ fontSize: 10 }} />
          <Bar dataKey="avg" name="avg" fill="#6366f1" radius={[2, 2, 0, 0]} />
          <Bar dataKey="p95" name="p95" fill="#f59e0b" radius={[2, 2, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Signal quality placeholder (IC / Sharpe) — scaffolding for Victoria data
// ---------------------------------------------------------------------------
function SignalQualityPlaceholder() {
  // Placeholder data until Victoria API is wired in
  const data = [
    { t: "T-9", ic: 0.0 },
    { t: "T-8", ic: 0.0 },
    { t: "T-7", ic: 0.0 },
    { t: "T-6", ic: 0.0 },
    { t: "T-5", ic: 0.0 },
    { t: "T-4", ic: 0.0 },
    { t: "T-3", ic: 0.0 },
    { t: "T-2", ic: 0.0 },
    { t: "T-1", ic: 0.0 },
    { t: "NOW", ic: 0.0 },
  ];
  return (
    <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm font-medium text-white">Signal Quality (IC)</p>
        <span className="text-xs text-gray-600 italic">wired to Victoria API</span>
      </div>
      <div className="h-32">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} />
            <XAxis dataKey="t" tick={TICK_STYLE} />
            <YAxis width={35} tick={TICK_STYLE} domain={[-0.1, 0.1]} />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              formatter={(v: number) => [v.toFixed(4), "IC"]}
            />
            <ReferenceLine y={0} stroke="#6b7280" strokeWidth={1} />
            <Area
              type="monotone"
              dataKey="ic"
              name="IC"
              stroke="#10b981"
              fill="#10b98130"
              dot={false}
              strokeWidth={1.5}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <p className="text-xs text-gray-600 mt-2 text-center">
        No IC history — connect Victoria trading node to populate
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function Metrics() {
  const [nodes, setNodes] = useState<Node[]>([]);
  const [histories, setHistories] = useState<Record<string, { ms: number }[]>>({});

  useEffect(() => {
    client
      .listNodes({})
      .then(async (r) => {
        setNodes(r.nodes);
        const histMap: Record<string, { ms: number }[]> = {};
        await Promise.all(
          r.nodes.map(async (n) => {
            const nr = await client.getNode({ nodeId: n.nodeId }).catch(() => null);
            if (nr) {
              histMap[n.nodeId] = nr.latencyHistory.map((p) => ({ ms: p.durationMs }));
            }
          })
        );
        setHistories(histMap);
      })
      .catch(console.error);
  }, []);

  return (
    <div className="space-y-8">
      <h1 className="text-lg font-semibold text-white">Metrics</h1>

      {/* Node execution latency */}
      <Section title="Node Execution Latency">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {nodes.map((n) => (
            <NodeLatencyCard key={n.nodeId} node={n} history={histories[n.nodeId] ?? []} />
          ))}
          {nodes.length === 0 && (
            <div className="col-span-2 bg-gray-800 rounded-xl border border-gray-700 p-6">
              <EmptyChart label="No nodes registered — run the orchestrator first" />
            </div>
          )}
        </div>
      </Section>

      {/* P95 vs avg latency comparison */}
      <Section title="P95 vs Avg Latency">
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
          <P95ComparisonChart nodes={nodes} />
        </div>
      </Section>

      {/* Cycle throughput */}
      <Section title="Cycle Throughput">
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
          <p className="text-xs text-gray-500 mb-3">
            Total executions and average latency per node. Red dashed line = 5% error threshold.
          </p>
          <CycleThroughputChart nodes={nodes} />
        </div>
      </Section>

      {/* Error rates */}
      <Section title="Error Rate by Node">
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
          <p className="text-xs text-gray-500 mb-3">
            Percentage of executions that resulted in errors. Dashed line = 5% threshold.
          </p>
          <ErrorRateChart nodes={nodes} />
        </div>
      </Section>

      {/* Signal quality (Victoria) */}
      <Section title="Signal Quality (Victoria)">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <SignalQualityPlaceholder />
          <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
            <div className="flex items-center justify-between mb-3">
              <p className="text-sm font-medium text-white">Sharpe (Rolling 30d)</p>
              <span className="text-xs text-gray-600 italic">wired to Victoria API</span>
            </div>
            <EmptyChart label="No Sharpe history — connect Victoria to populate" />
          </div>
        </div>
      </Section>
    </div>
  );
}
