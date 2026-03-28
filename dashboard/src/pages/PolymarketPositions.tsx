import {
  BookOpen,
  TrendingUp,
  TrendingDown,
  Activity,
  DollarSign,
  Layers,
  AlertCircle,
  CheckCircle,
  Minus,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type OrderBookLevel = { price: number; size: number };

type OrderBook = {
  token_id: string;
  market: string;
  bids: OrderBookLevel[];
  asks: OrderBookLevel[];
  best_bid: number;
  best_ask: number;
  mid: number;
};

type SmartMoneySignal = {
  direction: "bull" | "bear" | "neutral";
  confidence: number;
  imbalance_ratio: number;
  bid_depth_usdc: number;
  ask_depth_usdc: number;
  aligned: boolean;
};

type CLOBPosition = {
  id: string;
  condition_id: string;
  market: string;
  outcome: "YES" | "NO";
  size_usdc: number;
  entry_price: number;
  current_price: number;
  pnl_usdc: number;
  order_type: "limit" | "market";
  status: "open" | "filled" | "cancelled";
  placed_at: string;
  paper: boolean;
  smart_money: SmartMoneySignal;
  order_book: OrderBook;
};

// ---------------------------------------------------------------------------
// Mock data — replace with API calls when backend is wired
// ---------------------------------------------------------------------------

const MOCK_POSITIONS: CLOBPosition[] = [
  {
    id: "pos-001",
    condition_id: "0x1a2b3c4d5e6f",
    market: "Will BTC close above $80K on April 30?",
    outcome: "YES",
    size_usdc: 250,
    entry_price: 0.58,
    current_price: 0.64,
    pnl_usdc: 25.86,
    order_type: "limit",
    status: "open",
    placed_at: "2026-03-28T09:14:00Z",
    paper: true,
    smart_money: {
      direction: "bull",
      confidence: 0.72,
      imbalance_ratio: 1.41,
      bid_depth_usdc: 18400,
      ask_depth_usdc: 13050,
      aligned: true,
    },
    order_book: {
      token_id: "0x1a2b3c4d5e6f-YES",
      market: "Will BTC close above $80K on April 30?",
      bids: [
        { price: 0.638, size: 420 },
        { price: 0.635, size: 880 },
        { price: 0.630, size: 1200 },
        { price: 0.625, size: 650 },
        { price: 0.620, size: 340 },
      ],
      asks: [
        { price: 0.642, size: 310 },
        { price: 0.645, size: 720 },
        { price: 0.650, size: 950 },
        { price: 0.655, size: 480 },
        { price: 0.660, size: 220 },
      ],
      best_bid: 0.638,
      best_ask: 0.642,
      mid: 0.64,
    },
  },
  {
    id: "pos-002",
    condition_id: "0x7f8e9d0c1b2a",
    market: "Will NYC avg temp exceed 85°F in July 2026?",
    outcome: "YES",
    size_usdc: 180,
    entry_price: 0.52,
    current_price: 0.57,
    pnl_usdc: 17.31,
    order_type: "limit",
    status: "open",
    placed_at: "2026-03-27T14:30:00Z",
    paper: true,
    smart_money: {
      direction: "bull",
      confidence: 0.61,
      imbalance_ratio: 1.28,
      bid_depth_usdc: 9200,
      ask_depth_usdc: 7180,
      aligned: true,
    },
    order_book: {
      token_id: "0x7f8e9d0c1b2a-YES",
      market: "Will NYC avg temp exceed 85°F in July 2026?",
      bids: [
        { price: 0.568, size: 380 },
        { price: 0.565, size: 710 },
        { price: 0.560, size: 920 },
        { price: 0.555, size: 480 },
        { price: 0.550, size: 200 },
      ],
      asks: [
        { price: 0.572, size: 290 },
        { price: 0.575, size: 540 },
        { price: 0.580, size: 760 },
        { price: 0.585, size: 390 },
        { price: 0.590, size: 170 },
      ],
      best_bid: 0.568,
      best_ask: 0.572,
      mid: 0.57,
    },
  },
  {
    id: "pos-003",
    condition_id: "0x3c4d5e6f7a8b",
    market: "Will ETH gas fees avg > 30 gwei in Q2 2026?",
    outcome: "NO",
    size_usdc: 120,
    entry_price: 0.42,
    current_price: 0.38,
    pnl_usdc: 11.43,
    order_type: "limit",
    status: "open",
    placed_at: "2026-03-26T11:45:00Z",
    paper: true,
    smart_money: {
      direction: "bear",
      confidence: 0.55,
      imbalance_ratio: 0.79,
      bid_depth_usdc: 5100,
      ask_depth_usdc: 6450,
      aligned: true,
    },
    order_book: {
      token_id: "0x3c4d5e6f7a8b-NO",
      market: "Will ETH gas fees avg > 30 gwei in Q2 2026?",
      bids: [
        { price: 0.378, size: 290 },
        { price: 0.375, size: 560 },
        { price: 0.370, size: 740 },
        { price: 0.365, size: 380 },
        { price: 0.360, size: 160 },
      ],
      asks: [
        { price: 0.382, size: 420 },
        { price: 0.385, size: 830 },
        { price: 0.390, size: 1100 },
        { price: 0.395, size: 560 },
        { price: 0.400, size: 240 },
      ],
      best_bid: 0.378,
      best_ask: 0.382,
      mid: 0.38,
    },
  },
];

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SmartMoneyBadge({ signal }: { signal: SmartMoneySignal }) {
  const pct = Math.round(signal.confidence * 100);
  if (signal.direction === "bull") {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/25">
        <TrendingUp size={10} />
        Bull {pct}%
      </span>
    );
  }
  if (signal.direction === "bear") {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold bg-red-500/15 text-red-400 border border-red-500/25">
        <TrendingDown size={10} />
        Bear {pct}%
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold bg-slate-700 text-slate-400 border border-slate-600">
      <Minus size={10} />
      Neutral
    </span>
  );
}

function AlignedBadge({ aligned }: { aligned: boolean }) {
  return aligned ? (
    <span className="inline-flex items-center gap-1 text-xs text-emerald-400">
      <CheckCircle size={11} />
      Aligned
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-xs text-amber-400">
      <AlertCircle size={11} />
      Diverges
    </span>
  );
}

function OrderBookDepth({ book }: { book: OrderBook }) {
  const maxSize = Math.max(
    ...book.bids.map((l) => l.size),
    ...book.asks.map((l) => l.size),
    1
  );

  return (
    <div className="grid grid-cols-2 gap-3">
      {/* Bids */}
      <div>
        <div className="text-xs text-slate-500 uppercase tracking-wider mb-1.5">
          Bids
        </div>
        <div className="space-y-0.5">
          {book.bids.map((lv, i) => (
            <div key={i} className="relative flex items-center gap-2">
              <div
                className="absolute inset-y-0 left-0 bg-emerald-500/10 rounded-sm"
                style={{ width: `${(lv.size / maxSize) * 100}%` }}
              />
              <span className="relative z-10 text-xs font-mono text-emerald-400 w-12">
                {lv.price.toFixed(3)}
              </span>
              <span className="relative z-10 text-xs font-mono text-slate-400 text-right flex-1">
                {lv.size.toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      </div>
      {/* Asks */}
      <div>
        <div className="text-xs text-slate-500 uppercase tracking-wider mb-1.5">
          Asks
        </div>
        <div className="space-y-0.5">
          {book.asks.map((lv, i) => (
            <div key={i} className="relative flex items-center gap-2">
              <div
                className="absolute inset-y-0 left-0 bg-red-500/10 rounded-sm"
                style={{ width: `${(lv.size / maxSize) * 100}%` }}
              />
              <span className="relative z-10 text-xs font-mono text-red-400 w-12">
                {lv.price.toFixed(3)}
              </span>
              <span className="relative z-10 text-xs font-mono text-slate-400 text-right flex-1">
                {lv.size.toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function DepthBar({
  bidDepth,
  askDepth,
}: {
  bidDepth: number;
  askDepth: number;
}) {
  const total = bidDepth + askDepth || 1;
  const bidPct = (bidDepth / total) * 100;
  return (
    <div>
      <div className="flex justify-between text-xs text-slate-500 mb-1">
        <span>Bid ${(bidDepth / 1000).toFixed(1)}k</span>
        <span>Ask ${(askDepth / 1000).toFixed(1)}k</span>
      </div>
      <div className="h-1.5 rounded-full bg-slate-700 overflow-hidden flex">
        <div
          className="h-full bg-emerald-500 rounded-l-full transition-all"
          style={{ width: `${bidPct}%` }}
        />
        <div
          className="h-full bg-red-500 flex-1 rounded-r-full"
        />
      </div>
    </div>
  );
}

function PositionCard({ pos }: { pos: CLOBPosition }) {
  const pnlPositive = pos.pnl_usdc >= 0;
  const priceMove = pos.current_price - pos.entry_price;
  const pricePct = ((priceMove / pos.entry_price) * 100).toFixed(1);

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-700 flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <p className="text-sm text-slate-200 font-medium leading-snug truncate">
            {pos.market}
          </p>
          <div className="flex items-center gap-2 mt-1">
            <span
              className={`text-xs font-semibold px-1.5 py-0.5 rounded ${
                pos.outcome === "YES"
                  ? "bg-emerald-500/20 text-emerald-400"
                  : "bg-red-500/20 text-red-400"
              }`}
            >
              {pos.outcome}
            </span>
            {pos.paper && (
              <span className="text-xs bg-amber-500/15 text-amber-400 border border-amber-500/25 px-1.5 py-0.5 rounded">
                PAPER
              </span>
            )}
            <span className="text-xs text-slate-500">
              {new Date(pos.placed_at).toLocaleDateString()}
            </span>
          </div>
        </div>
        {/* P&L */}
        <div className="text-right shrink-0">
          <div
            className={`text-base font-bold font-mono ${
              pnlPositive ? "text-emerald-400" : "text-red-400"
            }`}
          >
            {pnlPositive ? "+" : ""}${pos.pnl_usdc.toFixed(2)}
          </div>
          <div
            className={`text-xs font-mono ${
              pnlPositive ? "text-emerald-500" : "text-red-500"
            }`}
          >
            {pricePct}%
          </div>
        </div>
      </div>

      {/* Body */}
      <div className="px-4 py-3 space-y-4">
        {/* Price + sizing row */}
        <div className="grid grid-cols-4 gap-3">
          <div>
            <div className="text-xs text-slate-500 mb-0.5">Size</div>
            <div className="text-sm font-mono text-slate-200">
              ${pos.size_usdc}
            </div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-0.5">Entry</div>
            <div className="text-sm font-mono text-slate-300">
              {(pos.entry_price * 100).toFixed(1)}¢
            </div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-0.5">Current</div>
            <div className="text-sm font-mono text-slate-200">
              {(pos.current_price * 100).toFixed(1)}¢
            </div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-0.5">Spread</div>
            <div className="text-sm font-mono text-slate-300">
              {(
                (pos.order_book.best_ask - pos.order_book.best_bid) *
                100
              ).toFixed(1)}
              ¢
            </div>
          </div>
        </div>

        {/* Smart money row */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">Smart money:</span>
            <SmartMoneyBadge signal={pos.smart_money} />
            <AlignedBadge aligned={pos.smart_money.aligned} />
          </div>
          <div className="text-xs text-slate-500 font-mono">
            ratio {pos.smart_money.imbalance_ratio.toFixed(2)}
          </div>
        </div>

        {/* Depth bar */}
        <DepthBar
          bidDepth={pos.smart_money.bid_depth_usdc}
          askDepth={pos.smart_money.ask_depth_usdc}
        />

        {/* Order book */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <BookOpen size={12} className="text-slate-500" />
            <span className="text-xs text-slate-500 uppercase tracking-wider">
              Order Book (top 5)
            </span>
            <span className="text-xs font-mono text-slate-400 ml-auto">
              mid {(pos.order_book.mid * 100).toFixed(1)}¢
            </span>
          </div>
          <OrderBookDepth book={pos.order_book} />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function PolymarketPositions() {
  const openPositions = MOCK_POSITIONS.filter((p) => p.status === "open");
  const totalPnl = openPositions.reduce((s, p) => s + p.pnl_usdc, 0);
  const totalSize = openPositions.reduce((s, p) => s + p.size_usdc, 0);
  const alignedCount = openPositions.filter(
    (p) => p.smart_money.aligned
  ).length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">
            CLOB Positions
          </h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Live order book · smart money consensus · paper mode
          </p>
        </div>
        <div className="flex items-center gap-2 bg-emerald-500/10 border border-emerald-500/30 rounded-lg px-3 py-1.5">
          <TrendingUp size={13} className="text-emerald-400" />
          <span className="text-sm text-emerald-400 font-semibold">
            +${totalPnl.toFixed(2)} unrealised
          </span>
        </div>
      </div>

      {/* Stats strip */}
      <div className="grid grid-cols-4 gap-4">
        {[
          {
            label: "Open Positions",
            value: String(openPositions.length),
            icon: Layers,
            color: "text-indigo-400",
            bg: "bg-indigo-500/10 border-indigo-500/20",
          },
          {
            label: "Deployed Capital",
            value: `$${totalSize.toLocaleString()}`,
            icon: DollarSign,
            color: "text-sky-400",
            bg: "bg-sky-500/10 border-sky-500/20",
          },
          {
            label: "Unrealised P&L",
            value: `+$${totalPnl.toFixed(2)}`,
            icon: TrendingUp,
            color: "text-emerald-400",
            bg: "bg-emerald-500/10 border-emerald-500/20",
          },
          {
            label: "Smart-Money Aligned",
            value: `${alignedCount}/${openPositions.length}`,
            icon: Activity,
            color: "text-violet-400",
            bg: "bg-violet-500/10 border-violet-500/20",
          },
        ].map(({ label, value, icon: Icon, color, bg }) => (
          <div
            key={label}
            className={`rounded-xl border p-4 ${bg} flex items-center gap-3`}
          >
            <Icon size={18} className={color} />
            <div>
              <div className="text-xs text-slate-500">{label}</div>
              <div className={`text-lg font-bold font-mono ${color}`}>
                {value}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Position cards */}
      <div className="space-y-4">
        {openPositions.map((pos) => (
          <PositionCard key={pos.id} pos={pos} />
        ))}
      </div>

      {/* CLOBClient status footer */}
      <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
          <div>
            <span className="text-xs font-semibold text-amber-400 uppercase tracking-wider">
              Paper Mode
            </span>
            <p className="text-xs text-slate-500 mt-0.5">
              Orders are logged but not executed.
              Set <code className="text-amber-300">POLYMARKET_LIVE=true</code> to enable live trading.
            </p>
          </div>
        </div>
        <div className="text-xs text-slate-500 font-mono">
          py-clob-client · POLYGON chain · CLOB API
        </div>
      </div>
    </div>
  );
}
