import React from 'react'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'

interface Props {
  label: string
  value: string | number
  sub?: string
  trend?: 'up' | 'down' | 'flat'
  loading?: boolean
  accent?: 'emerald' | 'amber' | 'rose' | 'slate' | 'sky'
}

const accentMap = {
  emerald: 'text-emerald-400',
  amber: 'text-amber-400',
  rose: 'text-rose-400',
  slate: 'text-slate-300',
  sky: 'text-sky-400',
}

export function MetricCard({ label, value, sub, trend, loading, accent = 'slate' }: Props) {
  const color = accentMap[accent]

  if (loading) {
    return (
      <div className="bg-slate-800 rounded-xl p-5 border border-slate-700/50">
        <div className="skeleton h-3 w-24 mb-3" />
        <div className="skeleton h-8 w-32 mb-2" />
        <div className="skeleton h-3 w-16" />
      </div>
    )
  }

  return (
    <div className="bg-slate-800 rounded-xl p-5 border border-slate-700/50 hover:border-slate-600 transition-colors">
      <p className="text-slate-400 text-xs font-medium uppercase tracking-wider mb-2">{label}</p>
      <p className={`text-3xl font-bold ${color} tabular-nums`}>{value}</p>
      {(sub || trend) && (
        <div className="flex items-center gap-1.5 mt-2">
          {trend === 'up' && <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />}
          {trend === 'down' && <TrendingDown className="w-3.5 h-3.5 text-rose-400" />}
          {trend === 'flat' && <Minus className="w-3.5 h-3.5 text-slate-500" />}
          {sub && <p className="text-slate-500 text-xs">{sub}</p>}
        </div>
      )}
    </div>
  )
}
