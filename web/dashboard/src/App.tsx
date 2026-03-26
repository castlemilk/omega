import React, { Suspense, lazy } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ProjectProvider } from './context/ProjectContext'
import { AppShell } from './components/AppShell'

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
const MemoryPage        = lazy(() => import('./pages/MemoryPage').then(m => ({ default: m.MemoryPage })))
const CorrelationsPage  = lazy(() => import('./pages/CorrelationsPage').then(m => ({ default: m.CorrelationsPage })))
const RegimePage        = lazy(() => import('./pages/RegimePage').then(m => ({ default: m.RegimePage })))
const TrainingPage      = lazy(() => import('./pages/TrainingPage').then(m => ({ default: m.TrainingPage })))

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
          <Suspense fallback={<PageLoader />}>
            <Routes>
              {/* Global platform routes */}
              <Route path="/" element={<GlobalOverview />} />
              <Route path="/coordination" element={<CoordinationPage />} />
              <Route path="/settings" element={<SettingsPage />} />

              {/* Per-project routes */}
              <Route path="/projects/:projectId" element={<ProjectOverview />} />
              <Route path="/projects/:projectId/trading"     element={<TradingPage />} />
              <Route path="/projects/:projectId/signals"     element={<SignalsPage />} />
              <Route path="/projects/:projectId/positions"   element={<PositionsPage />} />
              <Route path="/projects/:projectId/nodes"       element={<NodesPage />} />
              <Route path="/projects/:projectId/cycles"      element={<CyclesPage />} />
              <Route path="/projects/:projectId/adversarial" element={<AdversarialPage />} />
              <Route path="/projects/:projectId/health"      element={<HealthPage />} />
              <Route path="/projects/:projectId/improvement"   element={<ImprovementPage />} />
              <Route path="/projects/:projectId/memory"       element={<MemoryPage />} />
              <Route path="/projects/:projectId/correlations" element={<CorrelationsPage />} />
              <Route path="/projects/:projectId/regime"       element={<RegimePage />} />

              {/* Platform routes */}
              <Route path="/training" element={<TrainingPage />} />

              {/* Fallback */}
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </AppShell>
      </ProjectProvider>
    </BrowserRouter>
  )
}
