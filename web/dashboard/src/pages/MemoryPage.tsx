import React, { useState, useMemo } from 'react'
import { useParams } from 'react-router-dom'
import { Brain, Star, Filter, Globe, Clock, Tag } from 'lucide-react'

// ─── Mock data ────────────────────────────────────────────────────────────────

type MemoryType = 'episodic' | 'semantic'

interface Memory {
  id: string
  type: MemoryType
  content: string
  timestamp: string
  rating: number
  source: string
  projectId: string
  isCrossProject?: boolean
  tags: string[]
}

function generateMockMemories(): Memory[] {
  const episodicTemplates = [
    'Observed sharp volatility spike on BTC-USD at 14:32 UTC; momentum signal triggered 0.87 conviction long entry. Trade resolved +2.3% in 45 min.',
    'Cycle 847 completed with 63% win rate. Portfolio heat was elevated due to correlated positions in ETH and SOL. Auto-reduced exposure by 18%.',
    'Adversarial probe detected unusual pattern at node cluster C7. Flagged for manual review — turned out to be a data feed anomaly, not adversarial.',
    'Regime transition SIDEWAYS → BULL confirmed at cycle 812. Expanded position sizing from 0.8x to 1.2x. Subsequent 3-day PnL: +4.1%.',
    'Momentum signal underperformed during low-volume session (06:00–08:00 UTC). Half-life decay accelerated, weight auto-reduced from 22% to 14%.',
    'New market: MATIC-USD added to signal universe. Initial correlation with existing portfolio: 0.31 (acceptable). IC backtest: 0.038.',
    'Drew down 3.2% over 6 hours during Fed announcement. Signals conflicted — sentiment SHORT vs momentum LONG. System correctly reduced size to 0.4x.',
  ]
  const semanticTemplates = [
    'Momentum signals decay fastest during first 30 minutes post-announcement. Apply 0.5x weight multiplier during news windows.',
    'BTC dominance rising above 54% historically correlates with altcoin underperformance. Update position sizing heuristic for alts.',
    'Low-volume sessions (weekend UTC) show 2.1x higher false signal rate. Consider session filter in signal construction pipeline.',
    'Regime transitions typically preceded by 3-5 cycles of elevated cross-asset correlation. Monitor correlation matrix for early warning.',
    'Sentiment signal (social media) leads price by ~2.3 hours on average; optimal entry window is 60–90 min post-signal.',
    'Adversarial probes cluster around top-of-hour UTC timestamps. Hardened detection thresholds for 00min ± 5min window.',
    'Portfolio Sharpe improves 0.4 units when max per-trade exposure capped at 6% (vs current 8%). Consider tightening limits.',
  ]

  const sources = ['Victoria-v2', 'CycleEngine', 'AdversarialGuard', 'ManualReview', 'RegimeDetector', 'SignalEngine']
  const projectIds = ['victoria', 'polymarket', 'victoria']
  const tagSets = [
    ['momentum', 'volatility'],
    ['cycle', 'win-rate'],
    ['adversarial', 'anomaly'],
    ['regime', 'bull'],
    ['signal', 'decay'],
    ['onboarding', 'new-market'],
    ['risk', 'drawdown'],
  ]

  const memories: Memory[] = []
  const now = Date.now()

  for (let i = 0; i < 14; i++) {
    const isEpisodic = i < 7
    memories.push({
      id: `mem-${i}`,
      type: isEpisodic ? 'episodic' : 'semantic',
      content: isEpisodic ? episodicTemplates[i] : semanticTemplates[i - 7],
      timestamp: new Date(now - (i * 6 + Math.random() * 4) * 3600000).toISOString(),
      rating: Math.max(1, Math.min(5, 5 - Math.floor(i * 0.4))),
      source: sources[i % sources.length],
      projectId: projectIds[i % projectIds.length],
      isCrossProject: i % 4 === 3,
      tags: tagSets[i % tagSets.length],
    })
  }

  return memories.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
}

const ALL_MEMORIES = generateMockMemories()

// ─── Star rating ──────────────────────────────────────────────────────────────

function StarRating({ rating }: { rating: number }) {
  return (
    <div className="flex items-center gap-0.5">
      {Array.from({ length: 5 }).map((_, i) => (
        <Star
          key={i}
          className={`w-3 h-3 ${i < rating ? 'text-amber-400 fill-amber-400' : 'text-slate-600'}`}
        />
      ))}
    </div>
  )
}

// ─── Memory card ──────────────────────────────────────────────────────────────

function MemoryCard({ memory }: { memory: Memory }) {
  const typeColor = memory.type === 'episodic'
    ? 'bg-violet-500/15 text-violet-300 border-violet-500/30'
    : 'bg-sky-500/15 text-sky-300 border-sky-500/30'

  const relTime = (() => {
    const diff = Date.now() - new Date(memory.timestamp).getTime()
    const h = Math.floor(diff / 3600000)
    if (h < 1) return `${Math.floor(diff / 60000)}m ago`
    if (h < 24) return `${h}h ago`
    return `${Math.floor(h / 24)}d ago`
  })()

  return (
    <div
      className={`bg-slate-800 rounded-xl border transition-colors p-4 space-y-3 ${
        memory.isCrossProject ? 'border-amber-500/40 hover:border-amber-500/60' : 'border-slate-700/50 hover:border-slate-600'
      }`}
      data-testid={`memory-card-${memory.id}`}
    >
      {/* Header */}
      <div className="flex items-start gap-3 justify-between">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-xs font-medium px-2 py-0.5 rounded-full border ${typeColor} capitalize`}>
            {memory.type}
          </span>
          {memory.isCrossProject && (
            <span className="flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full border bg-amber-500/15 text-amber-300 border-amber-500/30">
              <Globe className="w-3 h-3" />
              cross-project
            </span>
          )}
          {memory.tags.map(tag => (
            <span key={tag} className="text-xs px-2 py-0.5 rounded-full bg-slate-700 text-slate-400">
              #{tag}
            </span>
          ))}
        </div>
        <StarRating rating={memory.rating} />
      </div>

      {/* Content */}
      <p className="text-slate-300 text-sm leading-relaxed">{memory.content}</p>

      {/* Footer */}
      <div className="flex items-center justify-between pt-1">
        <div className="flex items-center gap-3 text-xs text-slate-500">
          <span className="flex items-center gap-1">
            <Tag className="w-3 h-3" />
            {memory.source}
          </span>
          <span className="flex items-center gap-1">
            <Clock className="w-3 h-3" />
            {relTime}
          </span>
        </div>
        {memory.isCrossProject && (
          <span className="text-xs text-slate-500">from: {memory.projectId}</span>
        )}
      </div>
    </div>
  )
}

// ─── MemoryPage ────────────────────────────────────────────────────────────────

export function MemoryPage() {
  const { projectId = '' } = useParams<{ projectId: string }>()
  const [typeFilter, setTypeFilter] = useState<'all' | 'episodic' | 'semantic'>('all')
  const [ratingFilter, setRatingFilter] = useState<number>(0)
  const [showCrossProject, setShowCrossProject] = useState(false)

  const filtered = useMemo(() => {
    return ALL_MEMORIES.filter(m => {
      if (typeFilter !== 'all' && m.type !== typeFilter) return false
      if (ratingFilter > 0 && m.rating < ratingFilter) return false
      if (showCrossProject && !m.isCrossProject) return false
      return true
    })
  }, [typeFilter, ratingFilter, showCrossProject])

  const episodicCount = ALL_MEMORIES.filter(m => m.type === 'episodic').length
  const semanticCount = ALL_MEMORIES.filter(m => m.type === 'semantic').length
  const crossProjectCount = ALL_MEMORIES.filter(m => m.isCrossProject).length
  const avgRating = (ALL_MEMORIES.reduce((s, m) => s + m.rating, 0) / ALL_MEMORIES.length).toFixed(1)

  return (
    <div className="space-y-6" data-testid="memory-page">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 flex items-center gap-2">
            <Brain className="w-6 h-6 text-violet-400" />
            Memory Timeline
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            Episodic and semantic memories for project <span className="text-slate-300">{projectId}</span>
          </p>
        </div>
      </div>

      {/* Stats bar */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: 'Episodic', value: episodicCount, color: 'text-violet-400' },
          { label: 'Semantic', value: semanticCount, color: 'text-sky-400' },
          { label: 'Cross-project', value: crossProjectCount, color: 'text-amber-400' },
          { label: 'Avg Rating', value: avgRating + '★', color: 'text-emerald-400' },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-slate-800 rounded-xl border border-slate-700/50 p-4 text-center">
            <p className={`text-2xl font-bold tabular-nums ${color}`}>{value}</p>
            <p className="text-slate-500 text-xs mt-1">{label}</p>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <Filter className="w-4 h-4 text-slate-500" />

        {/* Type */}
        <div className="flex rounded-lg border border-slate-700 overflow-hidden">
          {(['all', 'episodic', 'semantic'] as const).map(t => (
            <button
              key={t}
              onClick={() => setTypeFilter(t)}
              className={`px-3 py-1.5 text-xs font-medium capitalize transition-colors ${
                typeFilter === t
                  ? 'bg-emerald-500/20 text-emerald-300'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        {/* Rating filter */}
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <span>Min rating:</span>
          <div className="flex rounded-lg border border-slate-700 overflow-hidden">
            {[0, 3, 4, 5].map(r => (
              <button
                key={r}
                onClick={() => setRatingFilter(r)}
                className={`px-2.5 py-1.5 text-xs font-medium transition-colors ${
                  ratingFilter === r
                    ? 'bg-emerald-500/20 text-emerald-300'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {r === 0 ? 'Any' : `${r}★+`}
              </button>
            ))}
          </div>
        </div>

        {/* Cross-project toggle */}
        <button
          onClick={() => setShowCrossProject(v => !v)}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors ${
            showCrossProject
              ? 'border-amber-500/40 bg-amber-500/15 text-amber-300'
              : 'border-slate-700 text-slate-400 hover:text-slate-200'
          }`}
        >
          <Globe className="w-3 h-3" />
          Cross-project only
        </button>

        <span className="ml-auto text-xs text-slate-500">{filtered.length} memories</span>
      </div>

      {/* Timeline */}
      <div className="space-y-3">
        {filtered.length === 0 ? (
          <div className="text-center py-16 text-slate-500 text-sm flex flex-col items-center gap-2">
            <Brain className="w-8 h-8 text-slate-600" />
            No memories match current filters
          </div>
        ) : (
          filtered.map(m => <MemoryCard key={m.id} memory={m} />)
        )}
      </div>
    </div>
  )
}
