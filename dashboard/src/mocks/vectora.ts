// ---------------------------------------------------------------------------
// VECTORA mock data — deterministic seeded PRNG, same seed = same data.
// Replace data-fetching calls with real Connect-ES hooks when backend is ready.
// ---------------------------------------------------------------------------

// Seeded PRNG (Mulberry32)
function mulberry32(seed: number): () => number {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const rng = mulberry32(42);
const rand = () => rng();
const randn = () => {
  const u = Math.max(1e-12, rand()),
    v = rand();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
};

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
export interface PerfDataPoint {
  date: string;
  i: number;
  omega: number;
  btc: number;
  dd: number;
}

export interface BacktestStats {
  sharpeAnn: number;
  sortinoAnn: number;
  maxDDpct: number;
  calmar: number;
  sharpeIS: number;
  sharpeOOS: number;
  VaR: number;
  CVaR: number;
  meanR: number;
  stdR: number;
  annReturn: number;
  totalReturn: number;
  portfolioValue: number;
  maxDDDuration: number;
  winRate: number;
  profitFactor: number;
}

export interface Position {
  sym: string;
  side: "LONG" | "SHORT";
  size: number;
  entry: number;
  mark: number;
  upnl: number;
  pct: number;
  notional: number;
  leverage: number;
  var95: number;
}

export interface Trade {
  ts: string;
  sym: string;
  side: "LONG" | "SHORT";
  size: number;
  entry: number;
  exit: number;
  pnl: number;
  slippage: number;
  duration: string;
}

export interface Signal {
  name: string;
  avgIC: number;
  weight: number;
  halfLife: number;
  color: string;
  conviction: number;
  brierScore: number;
  currentValue: number;
  trend: "up" | "down" | "flat";
}

export interface AblationEntry {
  name: string;
  dSharpe: number;
  sig: boolean;
}

export interface Regime {
  name: string;
  sharpe: number;
  ret: number;
  trades: number;
  pct: number;
}

export interface CrashScenario {
  name: string;
  sym: string;
  dd: number;
  recov: number | null;
  sl: number;
  pnl: number;
  pass: boolean;
}

export interface AutonomyEvent {
  date: string;
  level: "PICO" | "SUPERVISED" | "AUTONOMOUS";
  dir: "↑" | "↓" | "";
  reason: string;
}

export interface FundingPoint {
  t: number;
  funding: number;
  oi: number;
}

export interface AdvPoint {
  t: number;
  flag: number;
  fp: number;
}

export interface TpePoint {
  t: number;
  score: number;
  best: number;
}

export interface AllocationSlice {
  name: string;
  value: number;
  color: string;
}

// ---------------------------------------------------------------------------
// Generate performance data (504 trading days, seed=42)
// ---------------------------------------------------------------------------
const N = 504;
export const TRAIN_END = Math.floor(N * 0.6);

function buildData(): {
  perfData: PerfDataPoint[];
  labels: string[];
  stats: BacktestStats;
} {
  const labels: string[] = [];
  for (let d = new Date("2023-01-02"); labels.length < N; d.setDate(d.getDate() + 1))
    if (d.getDay() !== 0 && d.getDay() !== 6) labels.push(d.toISOString().slice(0, 10));

  const stRet: number[] = [];
  const equity = [100000];
  for (let i = 0; i < N; i++) {
    const r = 0.3 / 252 + (0.25 / Math.sqrt(252)) * randn();
    stRet.push(r);
    equity.push(equity[equity.length - 1] * (1 + r));
  }

  const btc = [100000];
  for (let i = 0; i < N; i++)
    btc.push(btc[btc.length - 1] * (1 + 0.4 / 252 + (0.8 / Math.sqrt(252)) * randn()));

  let peak = equity[0];
  const dd = equity.map((v) => {
    if (v > peak) peak = v;
    return peak > 0 ? ((v - peak) / peak) * 100 : 0;
  });

  // DD duration
  let maxDDDuration = 0,
    cur = 0;
  dd.forEach((v) => {
    if (v < -1) {
      cur++;
      maxDDDuration = Math.max(maxDDDuration, cur);
    } else cur = 0;
  });

  const meanR = stRet.reduce((s, r) => s + r, 0) / N;
  const stdR = Math.sqrt(stRet.map((r) => (r - meanR) ** 2).reduce((s, v) => s + v, 0) / (N - 1));
  const sharpeAnn = (meanR / stdR) * Math.sqrt(252);

  const down = stRet.filter((r) => r < 0);
  const dsStd = Math.sqrt(down.map((r) => r ** 2).reduce((s, v) => s + v, 0) / (down.length - 1));
  const sortinoAnn = (meanR / dsStd) * Math.sqrt(252);
  const maxDDpct = Math.min(...dd) / 100;
  const calmar = (meanR * 252) / Math.abs(maxDDpct);

  const inS = stRet.slice(0, TRAIN_END);
  const outS = stRet.slice(TRAIN_END);
  const mIS = inS.reduce((s, r) => s + r, 0) / inS.length;
  const sIS = Math.sqrt(
    inS.map((r) => (r - mIS) ** 2).reduce((s, v) => s + v, 0) / (inS.length - 1)
  );
  const mOS = outS.reduce((s, r) => s + r, 0) / outS.length;
  const sOS = Math.sqrt(
    outS.map((r) => (r - mOS) ** 2).reduce((s, v) => s + v, 0) / (outS.length - 1)
  );
  const sharpeIS = (mIS / sIS) * Math.sqrt(252);
  const sharpeOOS = (mOS / sOS) * Math.sqrt(252);

  const sortedR = [...stRet].sort((a, b) => a - b);
  const vi = Math.floor(0.05 * N);
  const VaR = -sortedR[vi] * 100;
  const CVaR = (-sortedR.slice(0, vi + 1).reduce((s, r) => s + r, 0) / (vi + 1)) * 100;

  const wins = stRet.filter((r) => r > 0).length;
  const losses = stRet.filter((r) => r <= 0).length;
  const avgWin = stRet.filter((r) => r > 0).reduce((s, r) => s + r, 0) / wins;
  const avgLoss = Math.abs(stRet.filter((r) => r <= 0).reduce((s, r) => s + r, 0) / losses);

  const perfData: PerfDataPoint[] = labels
    .map((date, i) => ({
      date,
      i,
      omega: +(equity[i + 1]?.toFixed(0) ?? 0),
      btc: +(btc[i + 1]?.toFixed(0) ?? 0),
      dd: +(dd[i + 1]?.toFixed(2) ?? 0),
    }))
    .filter((d) => d.omega > 0);

  return {
    perfData,
    labels,
    stats: {
      sharpeAnn,
      sortinoAnn,
      maxDDpct,
      calmar,
      sharpeIS,
      sharpeOOS,
      VaR,
      CVaR,
      meanR,
      stdR,
      annReturn: meanR * 252,
      totalReturn: (equity[N] - equity[0]) / equity[0],
      portfolioValue: equity[N],
      maxDDDuration,
      winRate: wins / N,
      profitFactor: avgWin / avgLoss,
    },
  };
}

const { perfData, labels, stats } = buildData();
export { perfData, labels };
export const backtestStats: BacktestStats = stats;

// ---------------------------------------------------------------------------
// Funding / OI series
// ---------------------------------------------------------------------------
export const fundingData: FundingPoint[] = Array.from({ length: 60 }, (_, i) => ({
  t: i + 1,
  funding: +(0.01 + 0.015 * Math.sin(i / 8) + 0.008 * randn()).toFixed(4),
  oi: +(8.2 + 1.5 * Math.sin(i / 12) + 0.5 * randn()).toFixed(2),
}));

export const latestFunding = fundingData[fundingData.length - 1].funding;
export const latestOI = fundingData[fundingData.length - 1].oi;

// ---------------------------------------------------------------------------
// Signal ablation
// ---------------------------------------------------------------------------
export const ablation: AblationEntry[] = [
  { name: "OrderFlow", dSharpe: 0.58, sig: true },
  { name: "CrossAsset", dSharpe: 0.44, sig: true },
  { name: "Microstructure", dSharpe: 0.31, sig: true },
  { name: "Sentiment", dSharpe: 0.19, sig: false },
  { name: "Ring1", dSharpe: 0.42, sig: true },
  { name: "Memory", dSharpe: 0.18, sig: false },
  { name: "TPE", dSharpe: 0.11, sig: false },
];

// ---------------------------------------------------------------------------
// Market regimes
// ---------------------------------------------------------------------------
export const regimes: Regime[] = [
  { name: "RISK-ON", sharpe: 1.38, ret: 36.4, trades: 51, pct: 30 },
  { name: "RISK-OFF", sharpe: 0.62, ret: 12.1, trades: 38, pct: 24 },
  { name: "DELEVERAGE", sharpe: 0.44, ret: 8.7, trades: 29, pct: 20 },
  { name: "ACCUMULATION", sharpe: 0.89, ret: 19.3, trades: 46, pct: 26 },
];
export const currentRegimeIdx = 0;

// ---------------------------------------------------------------------------
// Crash replay
// ---------------------------------------------------------------------------
export const crashes: CrashScenario[] = [
  { name: "COVID Mar 2020", sym: "BTCUSDT", dd: 8.4, recov: 12, sl: 0, pnl: 2.1, pass: true },
  {
    name: "China Ban May 2021",
    sym: "BTCUSDT",
    dd: 12.7,
    recov: 18,
    sl: 1,
    pnl: -1.8,
    pass: true,
  },
  {
    name: "LUNA May 2022",
    sym: "LUNAUSDT",
    dd: 94.2,
    recov: null,
    sl: 2,
    pnl: -89.4,
    pass: false,
  },
  { name: "FTX Nov 2022", sym: "BTCUSDT", dd: 18.3, recov: 21, sl: 1, pnl: -3.2, pass: true },
  { name: "Flash Aug 2023", sym: "BTCUSDT", dd: 6.1, recov: 4, sl: 0, pnl: 0.4, pass: true },
];

// ---------------------------------------------------------------------------
// Adversarial health
// ---------------------------------------------------------------------------
export const advSeries: AdvPoint[] = Array.from({ length: 60 }, (_, i) => ({
  t: i + 1,
  flag: Math.max(0, 0.08 + 0.04 * Math.sin(i / 5) + 0.025 * randn()),
  fp: Math.max(0, 0.02 + 0.01 * randn()),
}));

// ---------------------------------------------------------------------------
// TPE convergence
// ---------------------------------------------------------------------------
export const tpeSeries: TpePoint[] = (() => {
  let best = 0.2;
  return Array.from({ length: 200 }, (_, i) => {
    const s = 0.3 + 0.8 * (1 - Math.exp(-i / 60)) + 0.12 * randn();
    if (s > best) best = s;
    return { t: i + 1, score: +s.toFixed(4), best: +best.toFixed(4) };
  });
})();

// ---------------------------------------------------------------------------
// Autonomy history
// ---------------------------------------------------------------------------
export const autonomyHistory: AutonomyEvent[] = [
  { date: "2023-01-02", level: "PICO", dir: "", reason: "system_init" },
  { date: "2023-04-15", level: "SUPERVISED", dir: "↑", reason: "sharpe=0.58" },
  { date: "2023-06-20", level: "PICO", dir: "↓", reason: "drawdown 21%" },
  { date: "2023-09-01", level: "SUPERVISED", dir: "↑", reason: "sharpe=0.61" },
  { date: "2024-01-10", level: "AUTONOMOUS", dir: "↑", reason: "sharpe=1.12" },
];
export const CURRENT_LEVEL = "AUTONOMOUS";

// ---------------------------------------------------------------------------
// Signal generators (with Brier score accuracy)
// ---------------------------------------------------------------------------
export const signals: Signal[] = [
  {
    name: "ORDERFLOW (VPIN)",
    avgIC: 0.0812,
    weight: 0.34,
    halfLife: 7,
    color: "#00ff00",
    conviction: 0.82,
    brierScore: 0.21,
    currentValue: 0.73,
    trend: "up",
  },
  {
    name: "CROSS-ASSET",
    avgIC: 0.0631,
    weight: 0.26,
    halfLife: 9,
    color: "#00ffcc",
    conviction: 0.67,
    brierScore: 0.24,
    currentValue: 0.58,
    trend: "up",
  },
  {
    name: "MICROSTRUCTURE",
    avgIC: 0.0478,
    weight: 0.22,
    halfLife: 4,
    color: "#ffaa00",
    conviction: 0.54,
    brierScore: 0.27,
    currentValue: 0.41,
    trend: "flat",
  },
  {
    name: "SENTIMENT (FR+OI)",
    avgIC: 0.0293,
    weight: 0.18,
    halfLife: 3,
    color: "#009900",
    conviction: 0.38,
    brierScore: 0.31,
    currentValue: 0.29,
    trend: "down",
  },
  {
    name: "MOMENTUM",
    avgIC: 0.0521,
    weight: 0.2,
    halfLife: 12,
    color: "#aaffaa",
    conviction: 0.61,
    brierScore: 0.25,
    currentValue: 0.55,
    trend: "up",
  },
];

// ---------------------------------------------------------------------------
// Current positions
// ---------------------------------------------------------------------------
export const positions: Position[] = [
  {
    sym: "BTC/USDT",
    side: "LONG",
    size: 0.45,
    entry: 63420,
    mark: 64810,
    upnl: 625.5,
    pct: 2.19,
    notional: 29164.5,
    leverage: 2.0,
    var95: 1.42,
  },
  {
    sym: "ETH/USDT",
    side: "SHORT",
    size: 3.2,
    entry: 3180,
    mark: 3142,
    upnl: 121.6,
    pct: 1.19,
    notional: 10054.4,
    leverage: 1.5,
    var95: 1.81,
  },
  {
    sym: "SOL/USDT",
    side: "LONG",
    size: 12.0,
    entry: 148,
    mark: 152,
    upnl: 48.0,
    pct: 2.7,
    notional: 1824.0,
    leverage: 1.0,
    var95: 2.31,
  },
];

// ---------------------------------------------------------------------------
// Portfolio allocation (for pie chart)
// ---------------------------------------------------------------------------
export const allocation: AllocationSlice[] = [
  { name: "BTC/USDT", value: 29164, color: "#00ff00" },
  { name: "ETH/USDT", value: 10054, color: "#00ffcc" },
  { name: "SOL/USDT", value: 1824, color: "#ffaa00" },
  { name: "USDT Cash", value: 154688, color: "#006600" },
];

// ---------------------------------------------------------------------------
// Trade history
// ---------------------------------------------------------------------------
export const trades: Trade[] = [
  {
    ts: "2024-07-15 14:32",
    sym: "BTC/USDT",
    side: "LONG",
    size: 0.42,
    entry: 63420,
    exit: 64180,
    pnl: 319.2,
    slippage: 0.012,
    duration: "4h 18m",
  },
  {
    ts: "2024-07-14 09:11",
    sym: "ETH/USDT",
    side: "SHORT",
    size: 2.8,
    entry: 3240,
    exit: 3198,
    pnl: 117.6,
    slippage: 0.008,
    duration: "6h 02m",
  },
  {
    ts: "2024-07-13 22:55",
    sym: "BTC/USDT",
    side: "LONG",
    size: 0.35,
    entry: 62100,
    exit: 63800,
    pnl: 595.0,
    slippage: 0.015,
    duration: "11h 44m",
  },
  {
    ts: "2024-07-12 16:08",
    sym: "SOL/USDT",
    side: "SHORT",
    size: 15.0,
    entry: 158,
    exit: 163,
    pnl: -75.0,
    slippage: 0.022,
    duration: "2h 31m",
  },
  {
    ts: "2024-07-11 11:44",
    sym: "BTC/USDT",
    side: "LONG",
    size: 0.5,
    entry: 61500,
    exit: 62800,
    pnl: 650.0,
    slippage: 0.011,
    duration: "8h 55m",
  },
  {
    ts: "2024-07-10 08:22",
    sym: "ETH/USDT",
    side: "LONG",
    size: 3.1,
    entry: 3050,
    exit: 3140,
    pnl: 279.0,
    slippage: 0.009,
    duration: "5h 17m",
  },
  {
    ts: "2024-07-09 19:07",
    sym: "SOL/USDT",
    side: "SHORT",
    size: 10.0,
    entry: 162,
    exit: 158,
    pnl: 40.0,
    slippage: 0.018,
    duration: "3h 44m",
  },
  {
    ts: "2024-07-08 13:45",
    sym: "BTC/USDT",
    side: "LONG",
    size: 0.38,
    entry: 60800,
    exit: 61200,
    pnl: 152.0,
    slippage: 0.013,
    duration: "7h 20m",
  },
  {
    ts: "2024-07-07 07:30",
    sym: "ETH/USDT",
    side: "SHORT",
    size: 2.5,
    entry: 3320,
    exit: 3280,
    pnl: 100.0,
    slippage: 0.01,
    duration: "9h 05m",
  },
  {
    ts: "2024-07-06 21:15",
    sym: "SOL/USDT",
    side: "LONG",
    size: 20.0,
    entry: 138,
    exit: 142,
    pnl: 80.0,
    slippage: 0.019,
    duration: "4h 38m",
  },
  {
    ts: "2024-07-05 16:50",
    sym: "BTC/USDT",
    side: "SHORT",
    size: 0.25,
    entry: 63100,
    exit: 64500,
    pnl: -350.0,
    slippage: 0.016,
    duration: "12h 10m",
  },
  {
    ts: "2024-07-04 10:20",
    sym: "ETH/USDT",
    side: "LONG",
    size: 4.0,
    entry: 2950,
    exit: 3020,
    pnl: 280.0,
    slippage: 0.011,
    duration: "6h 48m",
  },
];
