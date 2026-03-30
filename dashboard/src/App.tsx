import { BrowserRouter, Routes, Route } from "react-router-dom";
import { useEffect, useRef, useState } from "react";
import Sidebar from "./components/layout/Sidebar";
import Header from "./components/layout/Header";
import ErrorBoundary from "./components/ErrorBoundary";
import { client } from "./client";
import type { SystemHealth as SystemHealthProto } from "./gen/omega/v1/types_pb";

import { ProjectProvider } from "./context/ProjectContext";
import Dashboard from "./pages/Dashboard";
import Projects from "./pages/Projects";
import Nodes from "./pages/Nodes";
import Traces from "./pages/Traces";
import Metrics from "./pages/Metrics";
import Issues from "./pages/Issues";
import Memory from "./pages/Memory";
import Convergence from "./pages/Convergence";
import Alignment from "./pages/Alignment";
import Adversarial from "./pages/Adversarial";
import Goals from "./pages/Goals";
import Challenges from "./pages/Challenges";
import Improvements from "./pages/Improvements";
import VictoriaDashboard from "./pages/VictoriaDashboard";
import VictoriaPortfolio from "./pages/VictoriaPortfolio";
import VictoriaSignals from "./pages/VictoriaSignals";
import VictoriaTrades from "./pages/VictoriaTrades";
import VictoriaBacktest from "./pages/VictoriaBacktest";
import PolymarketOverview from "./pages/PolymarketOverview";
import PolymarketMarkets from "./pages/PolymarketMarkets";
import PolymarketEdges from "./pages/PolymarketEdges";
import PolymarketWeather from "./pages/PolymarketWeather";
import PolymarketBets from "./pages/PolymarketBets";
import PolymarketPositions from "./pages/PolymarketPositions";
import SystemHealth from "./pages/SystemHealth";
import PerformanceMetrics from "./pages/PerformanceMetrics";
import ErrorLog from "./pages/ErrorLog";
import PipelineView from "./pages/PipelineView";
import ControlPlane from "./pages/ControlPlane";

export default function App() {
  const [health, setHealth] = useState<SystemHealthProto | null>(null);
  const [streamConnected, setStreamConnected] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    startStream();
    return () => abortRef.current?.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function startStream() {
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      setStreamConnected(true);
      for await (const event of client.streamEvents(
        { pollIntervalMs: 2000 },
        { signal: controller.signal }
      )) {
        if (event.payload.case === "healthUpdate") {
          setHealth(event.payload.value);
        }
      }
    } catch {
      setStreamConnected(false);
      setTimeout(startStream, 3000);
    }
  }

  return (
    <BrowserRouter>
      <ProjectProvider>
        <div className="flex min-h-screen bg-surface-900 text-gray-100">
          <Sidebar />
          <div className="flex-1 flex flex-col min-h-screen">
            <Header systemStatus={health?.status} connected={streamConnected} />
            <main className="flex-1 overflow-auto p-6">
              <Routes>
                <Route path="/" element={<Dashboard health={health} />} />
                <Route path="/projects" element={<Projects />} />
                <Route path="/nodes" element={<Nodes />} />
                <Route path="/traces" element={<Traces />} />
                <Route path="/metrics" element={<Metrics />} />
                <Route path="/issues" element={<Issues />} />
                <Route path="/memory" element={<Memory />} />
                <Route path="/convergence" element={<Convergence />} />
                <Route path="/alignment" element={<Alignment />} />
                <Route path="/adversarial" element={<Adversarial />} />
                <Route path="/goals" element={<Goals />} />
                <Route path="/challenges" element={<Challenges />} />
                <Route path="/improvements" element={<Improvements />} />
                <Route
                  path="/victoria"
                  element={
                    <ErrorBoundary fallbackLabel="VictoriaDashboard">
                      <VictoriaDashboard />
                    </ErrorBoundary>
                  }
                />
                <Route
                  path="/victoria/portfolio"
                  element={
                    <ErrorBoundary fallbackLabel="VictoriaPortfolio">
                      <VictoriaPortfolio />
                    </ErrorBoundary>
                  }
                />
                <Route
                  path="/victoria/signals"
                  element={
                    <ErrorBoundary fallbackLabel="VictoriaSignals">
                      <VictoriaSignals />
                    </ErrorBoundary>
                  }
                />
                <Route
                  path="/victoria/trades"
                  element={
                    <ErrorBoundary fallbackLabel="VictoriaTrades">
                      <VictoriaTrades />
                    </ErrorBoundary>
                  }
                />
                <Route
                  path="/victoria/backtest"
                  element={
                    <ErrorBoundary fallbackLabel="VictoriaBacktest">
                      <VictoriaBacktest />
                    </ErrorBoundary>
                  }
                />
                <Route path="/polymarket" element={<PolymarketOverview />} />
                <Route path="/polymarket/markets" element={<PolymarketMarkets />} />
                <Route path="/polymarket/edges" element={<PolymarketEdges />} />
                <Route path="/polymarket/weather" element={<PolymarketWeather />} />
                <Route path="/polymarket/bets" element={<PolymarketBets />} />
                <Route path="/polymarket/positions" element={<PolymarketPositions />} />
                {/* Observability */}
                <Route path="/health" element={<SystemHealth />} />
                <Route path="/perf" element={<PerformanceMetrics />} />
                <Route path="/errors" element={<ErrorLog />} />
                <Route path="/control-plane" element={<ControlPlane />} />
                <Route path="/projects/:id/pipeline" element={<PipelineView />} />
              </Routes>
            </main>
          </div>
        </div>
      </ProjectProvider>
    </BrowserRouter>
  );
}
