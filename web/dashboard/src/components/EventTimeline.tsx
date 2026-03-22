import React from 'react'
import { AlertTriangle, CheckCircle, Info, Zap, RefreshCw, Shield } from 'lucide-react'
import type { DashboardEvent } from '../lib/api'

const eventConfig: Record<string, { icon: React.ElementType; color: string; bg: string }> = {
  node_update:       { icon: RefreshCw,     color: 'text-sky-400',     bg: 'bg-sky-900/30' },
  cycle_complete:    { icon: CheckCircle,   color: 'text-emerald-400', bg: 'bg-emerald-900/30' },
  adversarial_alert: { icon: Shield,        color: 'text-rose-400',    bg: 'bg-rose-900/30' },
  improvement:       { icon: Zap,           color: 'text-amber-400',   bg: 'bg-amber-900/30' },
  warning:           { icon: AlertTriangle, color: 'text-amber-400',   bg: 'bg-amber-900/30' },
  info:              { icon: Info,          color: 'text-slate-400',   bg: 'bg-slate-700/30' },
}

function timeAgo(ts: string): string {
  const diff = (Date.now() - new Date(ts).getTime()) / 1000
  if (diff < 60) return `${Math.round(diff)}s ago`
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`
  return `${Math.round(diff / 3600)}h ago`
}

interface Props {
  events: DashboardEvent[]
  maxItems?: number
}

export function EventTimeline({ events, maxItems = 20 }: Props) {
  const displayed = events.slice(0, maxItems)

  if (displayed.length === 0) {
    return (
      <div className="flex items-center justify-center py-12 text-slate-500 text-sm">
        Waiting for events...
      </div>
    )
  }

  return (
    <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
      {displayed.map((event, i) => {
        const cfg = eventConfig[event.type] ?? eventConfig.info
        const Icon = cfg.icon
        return (
          <div key={i} className={`flex items-start gap-3 p-3 rounded-lg ${cfg.bg} border border-white/5`}>
            <div className={`mt-0.5 shrink-0 ${cfg.color}`}>
              <Icon className="w-4 h-4" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-slate-200 text-sm leading-snug">{event.message}</p>
              {event.node_id && (
                <p className="text-slate-500 text-xs mt-0.5 font-mono">{event.node_id}</p>
              )}
            </div>
            <span className="text-slate-500 text-xs shrink-0 tabular-nums">
              {event.timestamp ? timeAgo(event.timestamp) : ''}
            </span>
          </div>
        )
      })}
    </div>
  )
}
