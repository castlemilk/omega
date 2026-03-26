import React, { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  ArrowLeft, ChevronRight, CheckCircle, XCircle,
  Database, Zap, Link2, Shield, MessageSquare, PieChart, TrendingUp, Brain, Eye,
} from 'lucide-react'

// ─── Mock data ────────────────────────────────────────────────────────────────

type StepStatus = 'success' | 'error'

const PIPELINE_STEPS: {
  name: string
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  icon: React.ComponentType<any>
  duration: string
  status: StepStatus
}[] = [
  { name: 'Data Ingestion',         icon: Database,      duration: '2.3s', status: 'success' },
  { name: 'Signal Generation',      icon: Zap,           duration: '4.1s', status: 'success' },
  { name: 'On-Chain Analysis',      icon: Link2,         duration: '3.8s', status: 'success' },
  { name: 'Risk Assessment',        icon: Shield,        duration: '1.2s', status: 'success' },
  { name: 'Debate Gate',            icon: MessageSquare, duration: '6.7s', status: 'success' },
  { name: 'Portfolio Construction', icon: PieChart,      duration: '2.9s', status: 'success' },
  { name: 'Paper Trading',          icon: TrendingUp,    duration: '1.4s', status: 'success' },
  { name: 'Memory',                 icon: Brain,         duration: '3.2s', status: 'success' },
  { name: 'Reflection',             icon: Eye,           duration: '2.8s', status: 'success' },
]

// ─── CycleDetail ──────────────────────────────────────────────────────────────

export function CycleDetail() {
  const { projectId = '', cycleNumber = '' } = useParams<{ projectId: string; cycleNumber: string }>()
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const t = setTimeout(() => setLoading(false), 400)
    return () => clearTimeout(t)
  }, [])

  return (
    <div className="space-y-6" data-testid="cycle-detail">

      {/* Breadcrumb */}
      <div className="flex items-center gap-2 flex-wrap">
        <Link
          to={`/projects/${projectId}/cycles`}
          className="flex items-center gap-1.5 text-slate-400 hover:text-slate-200 transition-colors text-sm"
        >
          <ArrowLeft className="w-4 h-4" />
          Back
        </Link>
        <ChevronRight className="w-3 h-3 text-slate-600" />
        <span className="text-slate-400 text-sm capitalize">{projectId}</span>
        <ChevronRight className="w-3 h-3 text-slate-600" />
        <Link
          to={`/projects/${projectId}/cycles`}
          className="text-slate-400 hover:text-slate-200 text-sm transition-colors"
        >
          Cycles
        </Link>
        <ChevronRight className="w-3 h-3 text-slate-600" />
        <span className="text-slate-200 text-sm font-medium">#{cycleNumber}</span>
      </div>

      {/* Title */}
      {loading ? (
        <div className="skeleton h-14 rounded-xl" />
      ) : (
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Cycle #{cycleNumber}</h1>
          <p className="text-slate-400 text-sm mt-1">
            Executed 2026-03-26 at 14:23:11 UTC · Total duration 28.4s
          </p>
        </div>
      )}

      {/* Main: timeline + decisions sidebar */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

        {/* Timeline */}
        <div className="lg:col-span-2">
          {loading ? (
            <div className="space-y-2">
              {Array.from({ length: 9 }).map((_, i) => (
                <div key={i} className="skeleton h-16 rounded-xl" />
              ))}
            </div>
          ) : (
            <div className="bg-slate-800 rounded-xl border border-slate-700/50 overflow-hidden">
              <div className="px-5 py-4 border-b border-slate-700/50">
                <h3 className="text-sm font-semibold text-slate-300">Pipeline Execution</h3>
              </div>
              <div className="p-5 space-y-0">
                {PIPELINE_STEPS.map((step, index) => {
                  const Icon = step.icon
                  const isLast = index === PIPELINE_STEPS.length - 1
                  return (
                    <div key={step.name} className="flex items-stretch gap-4">
                      {/* Icon + connector line */}
                      <div className="flex flex-col items-center">
                        <div className={`w-9 h-9 rounded-full flex items-center justify-center shrink-0 mt-0.5 ${
                          step.status === 'success'
                            ? 'bg-emerald-900/50 border border-emerald-700/50'
                            : 'bg-rose-900/50 border border-rose-700/50'
                        }`}>
                          <Icon className={`w-4 h-4 ${
                            step.status === 'success' ? 'text-emerald-400' : 'text-rose-400'
                          }`} />
                        </div>
                        {!isLast && (
                          <div className="w-px bg-slate-700 flex-1 my-1" />
                        )}
                      </div>

                      {/* Step content */}
                      <div className={`flex-1 flex items-start justify-between ${
                        isLast ? 'py-2' : 'pb-5 pt-1'
                      }`}>
                        <div>
                          <p className="text-slate-200 text-sm font-medium">{step.name}</p>
                          <p className="text-slate-500 text-xs mt-0.5">
                            Step {index + 1} of {PIPELINE_STEPS.length}
                          </p>
                        </div>
                        <div className="flex items-center gap-2.5 shrink-0 mt-0.5">
                          <span className="bg-slate-700/80 text-slate-300 text-xs px-2.5 py-1 rounded-full font-mono">
                            {step.duration}
                          </span>
                          {step.status === 'success'
                            ? <CheckCircle className="w-4 h-4 text-emerald-400" />
                            : <XCircle className="w-4 h-4 text-rose-400" />
                          }
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>

        {/* Decisions sidebar */}
        <div className="space-y-4">
          {loading ? (
            <>
              <div className="skeleton h-56 rounded-xl" />
              <div className="skeleton h-32 rounded-xl" />
              <div className="skeleton h-28 rounded-xl" />
            </>
          ) : (
            <>
              {/* Decision summary */}
              <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
                <h3 className="text-sm font-semibold text-slate-300 mb-4">Decisions</h3>
                <div className="space-y-0 divide-y divide-slate-700/40">
                  {[
                    { label: 'Proposals Generated', value: '2',    color: 'text-slate-200' },
                    { label: 'Passed Gate',          value: '1',    color: 'text-emerald-400' },
                    { label: 'Blocked',              value: '1',    color: 'text-rose-400' },
                    { label: 'Disagreement Score',   value: '0.62', color: 'text-amber-400' },
                  ].map(({ label, value, color }) => (
                    <div key={label} className="flex items-center justify-between py-2.5">
                      <span className="text-slate-500 text-sm">{label}</span>
                      <span className={`text-sm font-bold tabular-nums ${color}`}>{value}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Block reason */}
              <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
                <h3 className="text-sm font-semibold text-slate-300 mb-2">Block Reason</h3>
                <p className="text-slate-400 text-sm leading-relaxed">
                  Proposal 2 blocked — disagreement score exceeded threshold (0.62 &gt; 0.50).
                  Agent vote: 3 LONG, 2 HOLD, 1 SHORT.
                </p>
              </div>

              {/* Outcome */}
              <div className="bg-slate-800 rounded-xl border border-slate-700/50 p-5">
                <h3 className="text-sm font-semibold text-slate-300 mb-3">Outcome</h3>
                <div className="space-y-2.5">
                  {[
                    { dot: 'bg-emerald-400', text: 'SOLUSDT LONG opened' },
                    { dot: 'bg-amber-400',   text: '1 improvement queued' },
                    { dot: 'bg-slate-500',   text: 'Memory updated (3 nodes)' },
                  ].map(({ dot, text }) => (
                    <div key={text} className="flex items-center gap-2">
                      <span className={`w-2 h-2 rounded-full shrink-0 ${dot}`} />
                      <span className="text-slate-300 text-sm">{text}</span>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
