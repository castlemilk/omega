import React, { Suspense, lazy } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ProjectProvider } from './context/ProjectContext'
import { AppShell } from './components/AppShell'
import { ErrorBoundary } from './components/ErrorBoundary'

// ─── Lazy page imports ────────────────────────────────────────────────────────

const GlobalOverview    = lazy(() => import('./pages/GlobalOverview').then(m => ({ default: m.GlobalOverview })))
const CoordinationPage  = lazy(() => import('./pages/CoordinationPage').then(m => ({ default: m.CoordinationPage })))
const SettingsPage      = lazy(() => import('./pages/SettingsPage').then(m => ({ default: m.SettingsPage })))

// Per-project pages
const ProjectOverview   = lazy(() => import('./pages/ProjectOverview').then(m => ({ default: m.ProjectOverview })))
const TradingPage       = lazy(() => import('./pages/TradingPage').then(m => ({ default: m.TradingPage })))
const SignalsPage       = lazy(() => import('./pages/SignalsPage').then(m => ({ default: m.SignalsPage })))
const PositionsPage     = lazy(() => import('./pages/PositionsPage').then(m => ({ default: m.PositionsPage })))
const NodesPage         = lazy(() => import('./pages/NodesPage').then(m => ({ default: m.NodesPage })))
const CyclesPage        = lazy(() => import('./pages/CyclesPage').then(m => ({ default: m.CyclesPage })))
const AdversarialPage   = lazy(() => import('./pages/AdversarialPage').then(m => ({ default: m.AdversarialPage })))
const HealthPage        = lazy(() => import('./pages/HealthPage').then(m => ({ default: m.HealthPage })))
const ImprovementPage   = lazy(() => import('./pages/ImprovementPage').then(m => ({ default: m.ImprovementPage })))

// Training progress page
const TrainingPage      = lazy(() => import('./pages/TrainingPage').then(m => ({ default: m.TrainingPage })))

// Polymarket-specific pages
const MarketsPage       = lazy(() => import('./pages/polymarket/MarketsPage').then(m => ({ default: m.MarketsPage })))
const EdgesPage         = lazy(() => import('./pages/polymarket/EdgesPage').then(m => ({ default: m.EdgesPage })))
const WeatherPage       = lazy(() => import('./pages/polymarket/WeatherPage').then(m => ({ default: m.WeatherPage })))
const BetsPage          = lazy(() => import('./pages/polymarket/BetsPage').then(m => ({ default: m.BetsPage })))

// ─── Fallback ────────────────────────────────────────────────────────────────

function PageLoader() {
  return (
    <div className="flex items-center justify-center h-64">
      <div className="w-6 h-6 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
    </div>
  )
}

// ─── App ─────────────────────────────────────────────────────────────────────

export default function App() {
  return (
    <BrowserRouter>
      <ProjectProvider>
        <AppShell>
          <ErrorBoundary>
            <Suspense fallback={<PageLoader />}>
              <Routes>
                {/* Global platform routes */}
                <Route path="/" element={<ErrorBoundary><GlobalOverview /></ErrorBoundary>} />
                <Route path="/training" element={<ErrorBoundary><TrainingPage /></ErrorBoundary>} />
                <Route path="/coordination" element={<ErrorBoundary><CoordinationPage /></ErrorBoundary>} />
                <Route path="/settings" element={<ErrorBoundary><SettingsPage /></ErrorBoundary>} />

                {/* Per-project routes */}
                <Route path="/projects/:projectId" element={<ErrorBoundary><ProjectOverview /></ErrorBoundary>} />
                <Route path="/projects/:projectId/trading"     element={<ErrorBoundary><TradingPage /></ErrorBoundary>} />
                <Route path="/projects/:projectId/signals"     element={<ErrorBoundary><SignalsPage /></ErrorBoundary>} />
                <Route path="/projects/:projectId/positions"   element={<ErrorBoundary><PositionsPage /></ErrorBoundary>} />
                <Route path="/projects/:projectId/nodes"       element={<ErrorBoundary><NodesPage /></ErrorBoundary>} />
                <Route path="/projects/:projectId/cycles"      element={<ErrorBoundary><CyclesPage /></ErrorBoundary>} />
                <Route path="/projects/:projectId/adversarial" element={<ErrorBoundary><AdversarialPage /></ErrorBoundary>} />
                <Route path="/projects/:projectId/health"      element={<ErrorBoundary><HealthPage /></ErrorBoundary>} />
                <Route path="/projects/:projectId/improvement" element={<ErrorBoundary><ImprovementPage /></ErrorBoundary>} />

                {/* Polymarket-specific routes */}
                <Route path="/projects/:projectId/markets" element={<ErrorBoundary><MarketsPage /></ErrorBoundary>} />
                <Route path="/projects/:projectId/edges"   element={<ErrorBoundary><EdgesPage /></ErrorBoundary>} />
                <Route path="/projects/:projectId/weather" element={<ErrorBoundary><WeatherPage /></ErrorBoundary>} />
                <Route path="/projects/:projectId/bets"    element={<ErrorBoundary><BetsPage /></ErrorBoundary>} />

                {/* Fallback */}
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </Suspense>
          </ErrorBoundary>
        </AppShell>
      </ProjectProvider>
    </BrowserRouter>
  )
}
