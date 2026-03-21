/**
 * Vectora API client — wraps Connect-ES calls to VectoraService.
 * Falls back to mock data when the API is unreachable.
 */
import { createClient } from "@connectrpc/connect";
import { createConnectTransport } from "@connectrpc/connect-web";
import { VectoraService } from "../gen/omega/v1/vectora_service_pb";
import type {
  AllocationSlice,
  BacktestStats,
  PerfDataPoint,
  Position,
  Signal,
  Trade,
  AblationEntry,
  Regime,
  CrashScenario,
  FundingPoint,
  AdvPoint,
  TpePoint,
} from "../mocks/vectora";
import * as mock from "../mocks/vectora";

// ---------------------------------------------------------------------------
// Client setup
// ---------------------------------------------------------------------------

const baseUrl = import.meta.env.VITE_API_URL ?? "";

const transport = createConnectTransport({ baseUrl });
const vectoraClient = createClient(VectoraService, transport);

// ---------------------------------------------------------------------------
// API availability state — set once on first failure, cleared on success
// ---------------------------------------------------------------------------

let _apiAvailable: boolean | null = null; // null = untested

export function isApiAvailable(): boolean {
  return _apiAvailable === true;
}

async function callApi<T>(
  fn: () => Promise<T>
): Promise<{ data: T; fromMock: false } | { data: null; fromMock: true }> {
  try {
    const data = await fn();
    _apiAvailable = true;
    return { data, fromMock: false };
  } catch {
    _apiAvailable = false;
    return { data: null, fromMock: true };
  }
}

// ---------------------------------------------------------------------------
// Portfolio
// ---------------------------------------------------------------------------

export interface PortfolioData {
  portfolioValue: number;
  unrealisedPnl: number;
  realisedPnl: number;
  totalPnl: number;
  totalReturn: number;
  annReturn: number;
  winRate: number;
  profitFactor: number;
  sharpe: number;
  annVol: number;
  allocation: AllocationSlice[];
  fromMock: boolean;
}

export async function fetchPortfolio(): Promise<PortfolioData> {
  const result = await callApi(() => vectoraClient.getPortfolio({}));

  if (result.fromMock) {
    const positions = mock.positions;
    const totalNotional = positions.reduce((s, p) => s + p.notional, 0);
    const cashValue = mock.allocation.find((a) => a.name === "USDT Cash")?.value ?? 0;
    const portfolioValue = totalNotional + cashValue;
    return {
      portfolioValue,
      unrealisedPnl: positions.reduce((s, p) => s + p.upnl, 0),
      realisedPnl: mock.backtestStats.totalReturn * portfolioValue * 0.1,
      totalPnl: positions.reduce((s, p) => s + p.upnl, 0),
      totalReturn: mock.backtestStats.totalReturn,
      annReturn: mock.backtestStats.annReturn,
      winRate: mock.backtestStats.winRate,
      profitFactor: mock.backtestStats.profitFactor,
      sharpe: mock.backtestStats.sharpeAnn,
      annVol: mock.backtestStats.stdR * Math.sqrt(252),
      allocation: mock.allocation,
      fromMock: true,
    };
  }

  const d = result.data;
  return {
    portfolioValue: d.portfolioValue,
    unrealisedPnl: d.unrealisedPnl,
    realisedPnl: d.realisedPnl,
    totalPnl: d.totalPnl,
    totalReturn: d.totalReturn,
    annReturn: d.annReturn,
    winRate: d.winRate,
    profitFactor: d.profitFactor,
    sharpe: d.sharpe,
    annVol: d.annVol,
    allocation: d.allocation.map((a) => ({
      name: a.name,
      value: a.value,
      color: a.color,
    })),
    fromMock: false,
  };
}

// ---------------------------------------------------------------------------
// Positions
// ---------------------------------------------------------------------------

export async function fetchPositions(): Promise<{ positions: Position[]; fromMock: boolean }> {
  const result = await callApi(() => vectoraClient.getPositions({}));

  if (result.fromMock) {
    return { positions: mock.positions, fromMock: true };
  }

  return {
    positions: result.data.positions.map((p) => ({
      sym: p.sym,
      side: p.side as "LONG" | "SHORT",
      size: p.size,
      entry: p.entry,
      mark: p.mark,
      upnl: p.upnl,
      pct: p.pct,
      notional: p.notional,
      leverage: p.leverage,
      var95: p.var95,
    })),
    fromMock: false,
  };
}

// ---------------------------------------------------------------------------
// PnL
// ---------------------------------------------------------------------------

export interface PnLData {
  unrealisedPnl: number;
  realisedPnl: number;
  totalPnl: number;
  totalReturn: number;
  annReturn: number;
  winRate: number;
  profitFactor: number;
  sharpe: number;
  annVol: number;
  maxDD: number;
  var95: number;
  cvar95: number;
  sortino: number;
  calmar: number;
  fromMock: boolean;
}

export async function fetchPnL(): Promise<PnLData> {
  const result = await callApi(() => vectoraClient.getPnL({}));

  if (result.fromMock) {
    const s = mock.backtestStats;
    const totalNotional = mock.positions.reduce((sum, p) => sum + p.notional, 0);
    return {
      unrealisedPnl: mock.positions.reduce((sum, p) => sum + p.upnl, 0),
      realisedPnl: s.totalReturn * totalNotional * 0.1,
      totalPnl: mock.positions.reduce((sum, p) => sum + p.upnl, 0),
      totalReturn: s.totalReturn,
      annReturn: s.annReturn,
      winRate: s.winRate,
      profitFactor: s.profitFactor,
      sharpe: s.sharpeAnn,
      annVol: s.stdR * Math.sqrt(252),
      maxDD: s.maxDDpct,
      var95: s.VaR,
      cvar95: s.CVaR,
      sortino: s.sortinoAnn,
      calmar: s.calmar,
      fromMock: true,
    };
  }

  const d = result.data;
  return {
    unrealisedPnl: d.unrealisedPnl,
    realisedPnl: d.realisedPnl,
    totalPnl: d.totalPnl,
    totalReturn: d.totalReturn,
    annReturn: d.annReturn,
    winRate: d.winRate,
    profitFactor: d.profitFactor,
    sharpe: d.sharpe,
    annVol: d.annVol,
    maxDD: d.maxDd,
    var95: d.var95,
    cvar95: d.cvar95,
    sortino: d.sortino,
    calmar: d.calmar,
    fromMock: false,
  };
}

// ---------------------------------------------------------------------------
// Signals
// ---------------------------------------------------------------------------

export interface SignalsData {
  signals: Signal[];
  compositeScore: number;
  compositeDirection: string;
  oosSharpe: number;
  fromMock: boolean;
}

export async function fetchSignals(): Promise<SignalsData> {
  const result = await callApi(() => vectoraClient.getSignals({}));

  if (result.fromMock) {
    const weighted = mock.signals.reduce((s, sig) => s + sig.conviction * sig.weight, 0);
    const totalW = mock.signals.reduce((s, sig) => s + sig.weight, 0);
    const composite = totalW > 0 ? weighted / totalW : 0;
    return {
      signals: mock.signals,
      compositeScore: composite,
      compositeDirection: composite > 0.5 ? "LONG" : composite < 0.4 ? "SHORT" : "NEUTRAL",
      oosSharpe: mock.backtestStats.sharpeOOS,
      fromMock: true,
    };
  }

  const d = result.data;
  return {
    signals: d.signals.map((s) => ({
      name: s.name,
      avgIC: s.avgIc,
      weight: s.weight,
      halfLife: s.halfLife,
      color: s.color,
      conviction: s.conviction,
      brierScore: s.brierScore,
      currentValue: s.currentValue,
      trend: s.trend as "up" | "down" | "flat",
    })),
    compositeScore: d.compositeScore,
    compositeDirection: d.compositeDirection,
    oosSharpe: d.oosSharpe,
    fromMock: false,
  };
}

export async function fetchSignalHistory(
  signalName: string,
  limit = 60
): Promise<{ points: { t: number; ic: number }[]; fromMock: boolean }> {
  const result = await callApi(() => vectoraClient.getSignalHistory({ signalName, limit }));

  if (result.fromMock) {
    // Generate deterministic IC history from mock signal
    const sig = mock.signals.find((s) => s.name === signalName);
    const baseIC = sig?.avgIC ?? 0.05;
    const points = Array.from({ length: limit }, (_, i) => ({
      t: i + 1,
      ic: +(baseIC + 0.03 * Math.sin(i / 5) + 0.015 * (Math.random() - 0.5)).toFixed(4),
    }));
    return { points, fromMock: true };
  }

  return {
    points: result.data.points.map((p) => ({ t: p.t, ic: p.ic })),
    fromMock: false,
  };
}

// ---------------------------------------------------------------------------
// Trades
// ---------------------------------------------------------------------------

export async function fetchTrades(
  symFilter = "",
  sideFilter = "",
  limit = 100
): Promise<{ trades: Trade[]; fromMock: boolean }> {
  const result = await callApi(() => vectoraClient.getTrades({ symFilter, sideFilter, limit }));

  if (result.fromMock) {
    let trades = mock.trades;
    if (symFilter) trades = trades.filter((t) => t.sym === symFilter);
    if (sideFilter) trades = trades.filter((t) => t.side === sideFilter);
    return { trades, fromMock: true };
  }

  return {
    trades: result.data.trades.map((t) => ({
      ts: t.ts,
      sym: t.sym,
      side: t.side as "LONG" | "SHORT",
      size: t.size,
      entry: t.entry,
      exit: t.exitPrice,
      pnl: t.pnl,
      slippage: t.slippage,
      duration: t.duration,
    })),
    fromMock: false,
  };
}

// ---------------------------------------------------------------------------
// Backtest
// ---------------------------------------------------------------------------

export async function fetchBacktestResults(): Promise<{
  stats: BacktestStats;
  trainEnd: number;
  fromMock: boolean;
}> {
  const result = await callApi(() => vectoraClient.getBacktestResults({}));

  if (result.fromMock) {
    return { stats: mock.backtestStats, trainEnd: mock.TRAIN_END, fromMock: true };
  }

  const s = result.data.stats;
  if (!s) return { stats: mock.backtestStats, trainEnd: mock.TRAIN_END, fromMock: true };

  return {
    stats: {
      sharpeAnn: s.sharpeAnn,
      sortinoAnn: s.sortinoAnn,
      maxDDpct: s.maxDdPct,
      calmar: s.calmar,
      sharpeIS: s.sharpeIs,
      sharpeOOS: s.sharpeOos,
      VaR: s.var,
      CVaR: s.cvar,
      meanR: s.meanR,
      stdR: s.stdR,
      annReturn: s.annReturn,
      totalReturn: s.totalReturn,
      portfolioValue: s.portfolioValue,
      maxDDDuration: s.maxDdDuration,
      winRate: s.winRate,
      profitFactor: s.profitFactor,
    },
    trainEnd: s.trainEnd,
    fromMock: false,
  };
}

// ---------------------------------------------------------------------------
// Equity curve
// ---------------------------------------------------------------------------

export async function fetchEquityCurve(
  limit = 0
): Promise<{ points: PerfDataPoint[]; trainEnd: number; fromMock: boolean }> {
  const result = await callApi(() => vectoraClient.getEquityCurve({ limit }));

  if (result.fromMock) {
    return { points: mock.perfData, trainEnd: mock.TRAIN_END, fromMock: true };
  }

  return {
    points: result.data.points.map((p) => ({
      date: p.date,
      i: p.i,
      omega: p.omega,
      btc: p.btc,
      dd: p.dd,
    })),
    trainEnd: result.data.trainEnd,
    fromMock: false,
  };
}

// ---------------------------------------------------------------------------
// Risk metrics
// ---------------------------------------------------------------------------

export interface RiskMetricsData {
  ablation: AblationEntry[];
  regimes: Regime[];
  currentRegimeIdx: number;
  crashes: CrashScenario[];
  fundingData: FundingPoint[];
  advSeries: AdvPoint[];
  tpeSeries: TpePoint[];
  latestFunding: number;
  latestOI: number;
  fromMock: boolean;
}

export async function fetchRiskMetrics(): Promise<RiskMetricsData> {
  const result = await callApi(() => vectoraClient.getRiskMetrics({}));

  if (result.fromMock) {
    return {
      ablation: mock.ablation,
      regimes: mock.regimes,
      currentRegimeIdx: mock.currentRegimeIdx,
      crashes: mock.crashes,
      fundingData: mock.fundingData,
      advSeries: mock.advSeries,
      tpeSeries: mock.tpeSeries,
      latestFunding: mock.latestFunding,
      latestOI: mock.latestOI,
      fromMock: true,
    };
  }

  const d = result.data;
  return {
    ablation: d.ablation.map((a) => ({ name: a.name, dSharpe: a.dSharpe, sig: a.sig })),
    regimes: d.regimes.map((r) => ({
      name: r.name,
      sharpe: r.sharpe,
      ret: r.ret,
      trades: r.trades,
      pct: r.pct,
    })),
    currentRegimeIdx: d.currentRegimeIdx,
    crashes: d.crashes.map((c) => ({
      name: c.name,
      sym: c.sym,
      dd: c.dd,
      recov: c.hasRecov ? c.recov : null,
      sl: c.sl,
      pnl: c.pnl,
      pass: c.pass,
    })),
    fundingData: d.fundingData.map((f) => ({ t: f.t, funding: f.funding, oi: f.oi })),
    advSeries: d.advSeries.map((a) => ({ t: a.t, flag: a.flag, fp: a.fp })),
    tpeSeries: d.tpeSeries.map((t) => ({ t: t.t, score: t.score, best: t.best })),
    latestFunding: d.latestFunding,
    latestOI: d.latestOi,
    fromMock: false,
  };
}
