import React, { useState } from 'react'
import { useParams } from 'react-router-dom'
import { Grid3X3, Info } from 'lucide-react'

// ─── Mock correlation data ────────────────────────────────────────────────────

const SIGNALS = [
  'Momentum', 'Sentiment', 'Volatility', 'Volume',
  'MeanRev', 'Carry', 'Trend', 'Breakout',
  'Funding', 'OBV', 'RSI',
]

// Generate a realistic symmetric correlation matrix
function buildMatrix(): number[][] {
  const n = SIGNALS.length
  const m: number[][] = Array.from({ length: n }, (_, i) =>
    Array.from({ length: n }, (_, j) => {
      if (i === j) return 1.0
      // Predefined realistic correlations
      const pairs: Record<string, number> = {
        '0-1': 0.42,  // Momentum-Sentiment
        '0-6': 0.71,  // Momentum-Trend
        '0-7': 0.55,  // Momentum-Breakout
        '1-4': -0.38, // Sentiment-MeanRev
        '2-3': 0.63,  // Volatility-Volume
        '2-9': 0.44,  // Volatility-OBV
        '3-9': 0.51,  // Volume-OBV
        '4-10': 0.67, // MeanRev-RSI
        '5-8': 0.82,  // Carry-Funding
        '6-7': 0.78,  // Trend-Breakout
        '0-4': -0.29, // Momentum-MeanRev
        '1-5': 0.23,  // Sentiment-Carry
        '2-8': -0.19, // Volatility-Funding
        '3-7': 0.34,  // Volume-Breakout
        '1-10': -0.22,// Sentiment-RSI
      }
      const key = `${Math.min(i, j)}-${Math.max(i, j)}`
      return pairs[key] ?? (Math.random() * 0.4 - 0.2)
    })
  )
  // Ensure symmetry
  for (let i = 0; i < n; i++)
    for (let j = 0; j < n; j++)
      if (i !== j) m[j][i] = m[i][j]
  return m
}

const MATRIX = buildMatrix()

// ─── Color scale ──────────────────────────────────────────────────────────────

function corrToColor(v: number): string {
  if (v === 1.0) return 'bg-slate-700 text-slate-300'
  if (v > 0.6)  return 'bg-emerald-500/80 text-emerald-950'
  if (v > 0.3)  return 'bg-emerald-500/40 text-emerald-200'
  if (v > 0.05) return 'bg-emerald-500/20 text-emerald-300'
  if (v > -0.05) return 'bg-slate-700/60 text-slate-400'
  if (v > -0.3)  return 'bg-rose-500/20 text-rose-300'
  if (v > -0.6)  return 'bg-rose-500/40 text-rose-200'
  return 'bg-rose-500/80 text-rose-950'
}

// ─── Scale legend ─────────────────────────────────────────────────────────────

function ColorScale() {
  const stops = [-1, -0.6, -0.3, 0, 0.3, 0.6, 1]
  return (
    <div className="flex items-center gap-1">
      <span className="text-xs text-slate-500 mr-2">−1</span>
      {stops.map((v, i) => (
        <div
          key={i}
          className={`w-8 h-5 rounded flex items-center justify-center text-xs font-bold ${corrToColor(v)}`}
        />
      ))}
      <span className="text-xs text-slate-500 ml-2">+1</span>
    </div>
  )
}

// ─── Tooltip state ────────────────────────────────────────────────────────────

interface Hover { row: number; col: number; val: number }

// ─── CorrelationsPage ──────────────────────────────────────────────────────────

export function CorrelationsPage() {
  const { projectId = '' } = useParams<{ projectId: string }>()
  const [hover, setHover] = useState<Hover | null>(null)

  // High-correlation pairs (|corr| > 0.5, non-diagonal)
  const highPairs = MATRIX.flatMap((row, i) =>
    row.map((v, j) => ({ i, j, v }))
  ).filter(({ i, j, v }) => i < j && Math.abs(v) > 0.5)
    .sort((a, b) => Math.abs(b.v) - Math.abs(a.v))

  return (
    <div className="space-y-6" data-testid="correlations-page">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 flex items-center gap-2">
            <Grid3X3 className="w-6 h-6 text-sky-400" />
            Signal Correlation Matrix
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            {SIGNALS.length}×{SIGNALS.length} pairwise correlations — project{' '}
            <span className="text-slate-300">{projectId}</span>
          </p>
        </div>
        <ColorScale />
      </div>

      {/* Hover info */}
      {hover && hover.row !== hover.col && (
        <div className="bg-slate-800 border border-slate-700 rounded-xl px-4 py-3 flex items-center gap-3 text-sm">
          <Info className="w-4 h-4 text-sky-400 shrink-0" />
          <span className="text-slate-300">
            <span className="text-slate-100 font-medium">{SIGNALS[hover.row]}</span>
            {' ↔ '}
            <span className="text-slate-100 font-medium">{SIGNALS[hover.col]}</span>
            {': '}
            <span className={hover.val > 0.3 ? 'text-emerald-400' : hover.val < -0.3 ? 'text-rose-400' : 'text-slate-300'}>
              {hover.val > 0 ? '+' : ''}{hover.val.toFixed(3)}
            </span>
            {Math.abs(hover.val) > 0.5 && (
              <span className="ml-2 text-amber-400 text-xs">⚠ High correlation — may cause redundancy</span>
            )}
          </span>
        </div>
      )}

      {/* Matrix */}
      <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-4 overflow-x-auto">
        <table className="border-collapse text-xs">
          <thead>
            <tr>
              <th className="w-20 p-0" />
              {SIGNALS.map(s => (
                <th key={s} className="p-0">
                  <div
                    className="w-14 text-center text-slate-400 font-medium pb-2"
                    style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)', height: '70px', lineHeight: '56px' }}
                  >
                    {s}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {MATRIX.map((row, i) => (
              <tr key={i}>
                <td className="pr-2 py-0.5 text-slate-400 font-medium text-right whitespace-nowrap">
                  {SIGNALS[i]}
                </td>
                {row.map((val, j) => (
                  <td key={j} className="p-0.5">
                    <div
                      className={`w-14 h-10 rounded flex items-center justify-center font-mono font-semibold cursor-default transition-all ${corrToColor(val)} ${
                        hover?.row === i && hover?.col === j ? 'ring-2 ring-white/40 scale-105' : ''
                      }`}
                      onMouseEnter={() => setHover({ row: i, col: j, val })}
                      onMouseLeave={() => setHover(null)}
                    >
                      {i === j ? '—' : val.toFixed(2)}
                    </div>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* High-correlation pairs */}
      <div>
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
          Notable Correlations
        </h2>
        <div className="grid grid-cols-2 gap-3">
          {highPairs.slice(0, 8).map(({ i, j, v }) => (
            <div key={`${i}-${j}`} className="bg-slate-800 rounded-xl border border-slate-700/50 p-3 flex items-center justify-between">
              <div>
                <p className="text-slate-200 text-sm font-medium">
                  {SIGNALS[i]} ↔ {SIGNALS[j]}
                </p>
                <p className="text-slate-500 text-xs mt-0.5">
                  {Math.abs(v) > 0.7 ? 'Very high' : 'High'} {v > 0 ? 'positive' : 'negative'} correlation
                </p>
              </div>
              <span className={`text-lg font-bold tabular-nums ${v > 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                {v > 0 ? '+' : ''}{v.toFixed(2)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
