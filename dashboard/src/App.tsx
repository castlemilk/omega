import { BrowserRouter, Routes, Route } from "react-router-dom";
import { useEffect, useRef, useState } from "react";
import Sidebar from "./components/layout/Sidebar";
import Header from "./components/layout/Header";
import { client } from "./client";
import type { SystemHealth } from "./gen/omega/v1/types_pb";

import Dashboard from "./pages/Dashboard";
import Nodes from "./pages/Nodes";
import Traces from "./pages/Traces";
import Metrics from "./pages/Metrics";
import Issues from "./pages/Issues";
import Memory from "./pages/Memory";
import Convergence from "./pages/Convergence";

export default function App() {
  const [health, setHealth] = useState<SystemHealth | null>(null);
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
      <div className="flex min-h-screen bg-surface-900 text-gray-100">
        <Sidebar />
        <div className="flex-1 flex flex-col min-h-screen">
          <Header systemStatus={health?.status} connected={streamConnected} />
          <main className="flex-1 overflow-auto p-6">
            <Routes>
              <Route path="/" element={<Dashboard health={health} />} />
              <Route path="/nodes" element={<Nodes />} />
              <Route path="/traces" element={<Traces />} />
              <Route path="/metrics" element={<Metrics />} />
              <Route path="/issues" element={<Issues />} />
              <Route path="/memory" element={<Memory />} />
              <Route path="/convergence" element={<Convergence />} />
            </Routes>
          </main>
        </div>
      </div>
    </BrowserRouter>
  );
}
