// Shared CRT terminal primitives for all Vectora pages.
import type { CSSProperties, ReactNode } from "react";

// ---------------------------------------------------------------------------
// Palette
// ---------------------------------------------------------------------------
export const T = {
  black: "#000000",
  green: "#00ff00",
  dim: "#006600",
  mid: "#009900",
  amber: "#ffaa00",
  red: "#ff2200",
  cyan: "#00ffcc",
  white: "#aaffaa",
  font: "'IBM Plex Mono','Courier New',Courier,monospace",
  glow: "0 0 8px #00ff00, 0 0 2px #00ff00",
  glowA: "0 0 8px #ffaa00",
  glowR: "0 0 8px #ff2200",
} as const;

// ---------------------------------------------------------------------------
// Recharts tooltip
// ---------------------------------------------------------------------------
interface TermTipPayload {
  color?: string;
  name?: string;
  value?: number | string;
}
interface TermTipProps {
  active?: boolean;
  payload?: TermTipPayload[];
  label?: string;
}

export function TermTip({ active, payload, label }: TermTipProps) {
  if (!active || !payload?.length) return null;
  return (
    <div
      style={{
        background: T.black,
        border: `1px solid ${T.green}`,
        padding: "6px 10px",
        fontFamily: T.font,
        fontSize: 10,
      }}
    >
      <p style={{ color: T.dim, marginBottom: 2 }}>{label}</p>
      {payload.map((p, i) => (
        <p key={i} style={{ color: p.color ?? T.green }}>
          &gt; {p.name}: {typeof p.value === "number" ? p.value.toFixed(4) : p.value}
        </p>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel wrapper
// ---------------------------------------------------------------------------
export function Panel({
  title,
  children,
  style,
}: {
  title?: string;
  children: ReactNode;
  style?: CSSProperties;
}) {
  return (
    <div
      style={{
        background: T.black,
        border: `1px solid ${T.green}`,
        padding: "8px 10px",
        fontFamily: T.font,
        ...style,
      }}
    >
      {title && (
        <div
          style={{
            fontSize: 10,
            color: T.dim,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            borderBottom: `1px solid ${T.dim}`,
            paddingBottom: 4,
            marginBottom: 6,
          }}
        >
          <span style={{ color: T.dim }}>$ </span>
          {title}
        </div>
      )}
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stat row
// ---------------------------------------------------------------------------
export function StatRow({
  label,
  value,
  color = T.green,
  glow = false,
}: {
  label: string;
  value: string;
  color?: string;
  glow?: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        marginBottom: 3,
        fontSize: 11,
      }}
    >
      <span style={{ color: T.dim }}>{label}</span>
      <span
        style={{
          color,
          fontWeight: "bold",
          textShadow: glow ? T.glow : "none",
          fontFamily: T.font,
        }}
      >
        {value}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page wrapper — breaks out of the Omega main's p-6 padding to fill full area
// ---------------------------------------------------------------------------
export function VectoraPage({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <div
      style={{
        background: T.black,
        color: T.green,
        fontFamily: T.font,
        margin: "-24px",
        minHeight: "calc(100vh - 56px)",
        overflowX: "auto",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------
export const fmt = (v: number, d = 2) => v.toFixed(d);
export const fmtPct = (v: number) => `${(v * 100).toFixed(1)}%`;
export const fmtUSDT = (v: number) =>
  `$${v.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
