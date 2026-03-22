import React from 'react'

type Status = 'healthy' | 'degraded' | 'critical' | 'active' | 'idle' | 'error' |
  'CLOSED' | 'OPEN' | 'HALF_OPEN' | 'PICO' | 'SUPERVISED' | 'AUTONOMOUS' |
  'completed' | 'running' | 'failed' | 'low' | 'medium' | 'high' | 'unhealthy'

const config: Record<string, { dot: string; bg: string; text: string; label?: string }> = {
  healthy:    { dot: 'bg-emerald-400', bg: 'bg-emerald-900/40', text: 'text-emerald-300' },
  active:     { dot: 'bg-emerald-400', bg: 'bg-emerald-900/40', text: 'text-emerald-300' },
  completed:  { dot: 'bg-emerald-400', bg: 'bg-emerald-900/40', text: 'text-emerald-300' },
  CLOSED:     { dot: 'bg-emerald-400', bg: 'bg-emerald-900/40', text: 'text-emerald-300' },
  AUTONOMOUS: { dot: 'bg-emerald-400', bg: 'bg-emerald-900/40', text: 'text-emerald-300' },
  low:        { dot: 'bg-emerald-400', bg: 'bg-emerald-900/40', text: 'text-emerald-300' },

  degraded:   { dot: 'bg-amber-400', bg: 'bg-amber-900/40', text: 'text-amber-300' },
  idle:       { dot: 'bg-amber-400', bg: 'bg-amber-900/40', text: 'text-amber-300' },
  HALF_OPEN:  { dot: 'bg-amber-400', bg: 'bg-amber-900/40', text: 'text-amber-300' },
  SUPERVISED: { dot: 'bg-amber-400', bg: 'bg-amber-900/40', text: 'text-amber-300' },
  running:    { dot: 'bg-amber-400 animate-pulse', bg: 'bg-amber-900/40', text: 'text-amber-300' },
  medium:     { dot: 'bg-amber-400', bg: 'bg-amber-900/40', text: 'text-amber-300' },

  critical:   { dot: 'bg-rose-400', bg: 'bg-rose-900/40', text: 'text-rose-300' },
  error:      { dot: 'bg-rose-400', bg: 'bg-rose-900/40', text: 'text-rose-300' },
  OPEN:       { dot: 'bg-rose-400', bg: 'bg-rose-900/40', text: 'text-rose-300' },
  failed:     { dot: 'bg-rose-400', bg: 'bg-rose-900/40', text: 'text-rose-300' },
  high:       { dot: 'bg-rose-400', bg: 'bg-rose-900/40', text: 'text-rose-300' },
  unhealthy:  { dot: 'bg-rose-400', bg: 'bg-rose-900/40', text: 'text-rose-300' },

  PICO:       { dot: 'bg-slate-400', bg: 'bg-slate-700/60', text: 'text-slate-300' },
}

interface Props {
  status: Status | string
  pulse?: boolean
  size?: 'sm' | 'md'
}

export function StatusBadge({ status, pulse, size = 'md' }: Props) {
  const c = config[status] ?? { dot: 'bg-slate-400', bg: 'bg-slate-700/60', text: 'text-slate-300' }
  const dotSize = size === 'sm' ? 'w-1.5 h-1.5' : 'w-2 h-2'
  const textSize = size === 'sm' ? 'text-xs' : 'text-xs'
  const px = size === 'sm' ? 'px-2 py-0.5' : 'px-2.5 py-1'

  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full ${px} ${c.bg} ${c.text} font-medium ${textSize}`}>
      <span className={`rounded-full ${dotSize} ${c.dot} ${pulse ? 'animate-pulse' : ''}`} />
      {status}
    </span>
  )
}
