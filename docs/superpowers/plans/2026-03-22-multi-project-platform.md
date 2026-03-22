# Multi-Project Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform Omega from a single-system (Victoria) dashboard into a multi-project platform where Omega is the execution/eval/improvement engine and Projects are configured instances driven by it.

**Architecture:** Add a `Project` protobuf message (with `pipeline_config`, `eval_config`, `improvement_config`, `domain`, `autonomy_level`, and `node_ids`) and a `ProjectService` with CRUD + node-assignment RPCs. The backend gets an in-memory `ProjectHandler` seeded with a default "Victoria" project. The frontend gains a `ProjectContext`, a Projects list page, a dynamic sidebar with project selector, and a dashboard that reads pipeline steps from the selected project rather than hardcoding Victoria's 9-step pipeline.

**Tech Stack:** protobuf + buf, Go + connectrpc, React 18 + TypeScript + Vite + shadcn/ui + Tailwind CSS + Connect-ES

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `proto/omega/v1/types.proto` | Add `PipelineStep`, `EvalConfig`, `ImprovementConfig`, `Project` messages |
| Create | `proto/omega/v1/project_service.proto` | `ProjectService` RPC definitions + request/response messages |
| Run | `buf generate` | Regenerate Go (`gen/go/`) and TypeScript (`dashboard/src/gen/`) |
| Create | `internal/handler/project_handler.go` | In-memory `ProjectHandler` implementing `ProjectServiceHandler` |
| Modify | `cmd/omega-api/main.go` | Wire `projectH` into mux; seed Victoria project on startup |
| Create | `dashboard/src/context/ProjectContext.tsx` | `ProjectContext` + `ProjectProvider`: projects list, selected project, setter |
| Modify | `dashboard/src/client.ts` | Export `projectClient` for `ProjectService` |
| Modify | `dashboard/src/App.tsx` | Wrap with `<ProjectProvider>`, add `/projects` and `/projects/:id/*` routes |
| Create | `dashboard/src/pages/Projects.tsx` | Projects list page (cards with name, domain, status, node count, pipeline steps) |
| Modify | `dashboard/src/components/layout/Sidebar.tsx` | Dynamic sidebar: OMEGA global section + project selector dropdown + selected project section |
| Modify | `dashboard/src/pages/Dashboard.tsx` | Pipeline visualization reads from `selectedProject.pipeline_config` instead of hardcoded steps |

---

## Task 1: Add Project types to types.proto

**Files:**
- Modify: `proto/omega/v1/types.proto`

- [ ] **Step 1: Append Project messages to types.proto**

Add the following at the end of `proto/omega/v1/types.proto` (before the final newline):

```protobuf
// ── Projects ────────────────────────────────────────────────────────────────

// PipelineStep represents one ordered step in a project's execution pipeline.
// node_type references a capability enum name from the global node registry.
message PipelineStep {
  string step_id    = 1;
  string name       = 2;  // display name, e.g. "DataIngestion"
  string node_type  = 3;  // maps to NodeCapability enum name, e.g. "DATA_INGESTION"
  string description = 4;
  int32  order      = 5;
  map<string, string> config = 6;
}

// EvalConfig declares which metrics matter for a project and their targets.
message EvalConfig {
  repeated string primary_metrics = 1;   // e.g. ["sharpe_ratio", "ic", "max_drawdown"]
  map<string, double> metric_targets = 2; // e.g. {"sharpe_ratio": 1.5, "ic": 0.05}
  string eval_frequency = 3;             // "per_cycle", "daily", "weekly"
}

// ImprovementConfig controls how Omega's improvement engine runs for a project.
message ImprovementConfig {
  bool   tpe_enabled         = 1;
  int32  tpe_trials          = 2;
  bool   adversarial_enabled = 3;
  int32  adversarial_rounds  = 4;
  bool   walk_forward_enabled = 5;
  map<string, string> extra  = 6;
}

// Project is a configured instance driven by the Omega platform.
// Omega is the execution/eval/improvement engine; Projects declare WHAT to run.
message Project {
  string project_id    = 1;
  string name          = 2;
  string description   = 3;
  // status: "active" | "paused" | "archived"
  string status        = 4;
  // domain: "crypto_quant" | "macro_research" | "options_arb" | "custom"
  string domain        = 5;
  // autonomy_level mirrors NodeRegistration.autonomy_level
  string autonomy_level = 6;
  // node_ids references nodes in the global Omega node registry
  repeated string node_ids = 7;
  // pipeline_config is the ordered execution pipeline for this project
  repeated PipelineStep pipeline_config = 8;
  EvalConfig        eval_config        = 9;
  ImprovementConfig improvement_config = 10;
  google.protobuf.Timestamp created_at = 11;
  google.protobuf.Timestamp updated_at = 12;
  map<string, string> metadata = 13;
}
```

- [ ] **Step 2: Verify proto file is syntactically valid**

```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/wizardly-rubin
buf lint proto/omega/v1/types.proto
```

Expected: no output (lint passes).

---

## Task 2: Create project_service.proto

**Files:**
- Create: `proto/omega/v1/project_service.proto`

- [ ] **Step 1: Write project_service.proto**

```protobuf
syntax = "proto3";

package omega.v1;

option go_package = "github.com/benebsworth/omega/gen/go/omega/v1;omegav1";

import "omega/v1/types.proto";
import "google/protobuf/timestamp.proto";

service ProjectService {
  rpc CreateProject(CreateProjectRequest)           returns (CreateProjectResponse);
  rpc GetProject(GetProjectRequest)                 returns (GetProjectResponse);
  rpc ListProjects(ListProjectsRequest)             returns (ListProjectsResponse);
  rpc UpdateProject(UpdateProjectRequest)           returns (UpdateProjectResponse);
  rpc DeleteProject(DeleteProjectRequest)           returns (DeleteProjectResponse);
  rpc AssignNodeToProject(AssignNodeToProjectRequest)   returns (AssignNodeToProjectResponse);
  rpc RemoveNodeFromProject(RemoveNodeFromProjectRequest) returns (RemoveNodeFromProjectResponse);
}

message CreateProjectRequest {
  string name          = 1;
  string description   = 2;
  string domain        = 3;
  string autonomy_level = 4;
  repeated string node_ids = 5;
  repeated PipelineStep pipeline_config = 6;
  EvalConfig        eval_config        = 7;
  ImprovementConfig improvement_config = 8;
  map<string, string> metadata = 9;
}
message CreateProjectResponse { Project project = 1; }

message GetProjectRequest  { string project_id = 1; }
message GetProjectResponse { Project project = 1; }

message ListProjectsRequest  {}
message ListProjectsResponse { repeated Project projects = 1; }

message UpdateProjectRequest {
  string project_id    = 1;
  string name          = 2;
  string description   = 3;
  string status        = 4;
  string domain        = 5;
  string autonomy_level = 6;
  repeated PipelineStep pipeline_config = 7;
  EvalConfig        eval_config        = 8;
  ImprovementConfig improvement_config = 9;
  map<string, string> metadata = 10;
}
message UpdateProjectResponse { Project project = 1; }

message DeleteProjectRequest  { string project_id = 1; }
message DeleteProjectResponse { bool success = 1; }

message AssignNodeToProjectRequest {
  string project_id = 1;
  string node_id    = 2;
}
message AssignNodeToProjectResponse { Project project = 1; }

message RemoveNodeFromProjectRequest {
  string project_id = 1;
  string node_id    = 2;
}
message RemoveNodeFromProjectResponse { Project project = 1; }
```

- [ ] **Step 2: Lint the new service proto**

```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/wizardly-rubin
buf lint proto/omega/v1/project_service.proto
```

Expected: no output.

---

## Task 3: Run buf generate

**Files:**
- Run: `buf generate` in repo root

- [ ] **Step 1: Generate code**

```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/wizardly-rubin
buf generate
```

Expected: new files in `gen/go/omega/v1/` (project_service.pb.go, project_service_grpc.pb.go or omegav1connect package) and `dashboard/src/gen/omega/v1/` (project_service_pb.ts, project_service_connect.ts or similar).

- [ ] **Step 2: Verify generated Go compiles**

```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/wizardly-rubin
go build ./...
```

Expected: exits 0 with no errors.

- [ ] **Step 3: Commit proto + generated code**

```bash
git add proto/omega/v1/types.proto proto/omega/v1/project_service.proto gen/ dashboard/src/gen/
git commit -m "feat(proto): add Project type and ProjectService RPC definitions"
```

---

## Task 4: Implement ProjectHandler (Go)

**Files:**
- Create: `internal/handler/project_handler.go`

- [ ] **Step 1: Write project_handler.go**

```go
package handler

import (
	"context"
	"fmt"
	"sync"
	"time"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/types/known/timestamppb"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"github.com/benebsworth/omega/gen/go/omega/v1/omegav1connect"
)

// ProjectHandler implements omegav1connect.ProjectServiceHandler with an
// in-memory store. All methods are safe for concurrent use.
type ProjectHandler struct {
	omegav1connect.UnimplementedProjectServiceHandler
	mu       sync.RWMutex
	projects map[string]*omegav1.Project
}

// NewProject creates a new in-memory ProjectHandler.
func NewProject() *ProjectHandler {
	return &ProjectHandler{
		projects: make(map[string]*omegav1.Project),
	}
}

// SeedProject adds a project to the store. Used for startup seeding.
func (h *ProjectHandler) SeedProject(p *omegav1.Project) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.projects[p.ProjectId] = p
}

func (h *ProjectHandler) CreateProject(
	_ context.Context, req *connect.Request[omegav1.CreateProjectRequest],
) (*connect.Response[omegav1.CreateProjectResponse], error) {
	now := timestamppb.Now()
	id := fmt.Sprintf("proj_%d", time.Now().UnixNano())
	p := &omegav1.Project{
		ProjectId:         id,
		Name:              req.Msg.Name,
		Description:       req.Msg.Description,
		Domain:            req.Msg.Domain,
		AutonomyLevel:     req.Msg.AutonomyLevel,
		Status:            "active",
		NodeIds:           req.Msg.NodeIds,
		PipelineConfig:    req.Msg.PipelineConfig,
		EvalConfig:        req.Msg.EvalConfig,
		ImprovementConfig: req.Msg.ImprovementConfig,
		Metadata:          req.Msg.Metadata,
		CreatedAt:         now,
		UpdatedAt:         now,
	}
	h.mu.Lock()
	h.projects[id] = p
	h.mu.Unlock()
	return connect.NewResponse(&omegav1.CreateProjectResponse{Project: p}), nil
}

func (h *ProjectHandler) GetProject(
	_ context.Context, req *connect.Request[omegav1.GetProjectRequest],
) (*connect.Response[omegav1.GetProjectResponse], error) {
	h.mu.RLock()
	p, ok := h.projects[req.Msg.ProjectId]
	h.mu.RUnlock()
	if !ok {
		return nil, connect.NewError(connect.CodeNotFound, fmt.Errorf("project %q not found", req.Msg.ProjectId))
	}
	return connect.NewResponse(&omegav1.GetProjectResponse{Project: p}), nil
}

func (h *ProjectHandler) ListProjects(
	_ context.Context, _ *connect.Request[omegav1.ListProjectsRequest],
) (*connect.Response[omegav1.ListProjectsResponse], error) {
	h.mu.RLock()
	out := make([]*omegav1.Project, 0, len(h.projects))
	for _, p := range h.projects {
		out = append(out, p)
	}
	h.mu.RUnlock()
	return connect.NewResponse(&omegav1.ListProjectsResponse{Projects: out}), nil
}

func (h *ProjectHandler) UpdateProject(
	_ context.Context, req *connect.Request[omegav1.UpdateProjectRequest],
) (*connect.Response[omegav1.UpdateProjectResponse], error) {
	h.mu.Lock()
	defer h.mu.Unlock()
	p, ok := h.projects[req.Msg.ProjectId]
	if !ok {
		return nil, connect.NewError(connect.CodeNotFound, fmt.Errorf("project %q not found", req.Msg.ProjectId))
	}
	if req.Msg.Name != "" {
		p.Name = req.Msg.Name
	}
	if req.Msg.Description != "" {
		p.Description = req.Msg.Description
	}
	if req.Msg.Status != "" {
		p.Status = req.Msg.Status
	}
	if req.Msg.Domain != "" {
		p.Domain = req.Msg.Domain
	}
	if req.Msg.AutonomyLevel != "" {
		p.AutonomyLevel = req.Msg.AutonomyLevel
	}
	if len(req.Msg.PipelineConfig) > 0 {
		p.PipelineConfig = req.Msg.PipelineConfig
	}
	if req.Msg.EvalConfig != nil {
		p.EvalConfig = req.Msg.EvalConfig
	}
	if req.Msg.ImprovementConfig != nil {
		p.ImprovementConfig = req.Msg.ImprovementConfig
	}
	p.UpdatedAt = timestamppb.Now()
	return connect.NewResponse(&omegav1.UpdateProjectResponse{Project: p}), nil
}

func (h *ProjectHandler) DeleteProject(
	_ context.Context, req *connect.Request[omegav1.DeleteProjectRequest],
) (*connect.Response[omegav1.DeleteProjectResponse], error) {
	h.mu.Lock()
	_, ok := h.projects[req.Msg.ProjectId]
	if ok {
		delete(h.projects, req.Msg.ProjectId)
	}
	h.mu.Unlock()
	if !ok {
		return nil, connect.NewError(connect.CodeNotFound, fmt.Errorf("project %q not found", req.Msg.ProjectId))
	}
	return connect.NewResponse(&omegav1.DeleteProjectResponse{Success: true}), nil
}

func (h *ProjectHandler) AssignNodeToProject(
	_ context.Context, req *connect.Request[omegav1.AssignNodeToProjectRequest],
) (*connect.Response[omegav1.AssignNodeToProjectResponse], error) {
	h.mu.Lock()
	defer h.mu.Unlock()
	p, ok := h.projects[req.Msg.ProjectId]
	if !ok {
		return nil, connect.NewError(connect.CodeNotFound, fmt.Errorf("project %q not found", req.Msg.ProjectId))
	}
	for _, id := range p.NodeIds {
		if id == req.Msg.NodeId {
			return connect.NewResponse(&omegav1.AssignNodeToProjectResponse{Project: p}), nil
		}
	}
	p.NodeIds = append(p.NodeIds, req.Msg.NodeId)
	p.UpdatedAt = timestamppb.Now()
	return connect.NewResponse(&omegav1.AssignNodeToProjectResponse{Project: p}), nil
}

func (h *ProjectHandler) RemoveNodeFromProject(
	_ context.Context, req *connect.Request[omegav1.RemoveNodeFromProjectRequest],
) (*connect.Response[omegav1.RemoveNodeFromProjectResponse], error) {
	h.mu.Lock()
	defer h.mu.Unlock()
	p, ok := h.projects[req.Msg.ProjectId]
	if !ok {
		return nil, connect.NewError(connect.CodeNotFound, fmt.Errorf("project %q not found", req.Msg.ProjectId))
	}
	filtered := p.NodeIds[:0]
	for _, id := range p.NodeIds {
		if id != req.Msg.NodeId {
			filtered = append(filtered, id)
		}
	}
	p.NodeIds = filtered
	p.UpdatedAt = timestamppb.Now()
	return connect.NewResponse(&omegav1.RemoveNodeFromProjectResponse{Project: p}), nil
}
```

- [ ] **Step 2: Verify it compiles**

```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/wizardly-rubin
go build ./internal/handler/...
```

Expected: exits 0.

---

## Task 5: Wire ProjectHandler into main.go + seed Victoria project

**Files:**
- Modify: `cmd/omega-api/main.go`

- [ ] **Step 1: Add projectH initialization after other handlers (~line 200)**

After the `nodeH` block (line ~213), add:

```go
// ── Project handler ───────────────────────────────────────────────────────
projectH := handler.NewProject()

// Seed the default Victoria project on startup.
projectH.SeedProject(victoriaProject())
```

- [ ] **Step 2: Add victoriaProject() helper function at end of main.go (outside main())**

```go
// victoriaProject returns the default "Victoria" crypto-quant project seed.
func victoriaProject() *omegav1.Project {
	now := timestamppb.Now()
	steps := []*omegav1.PipelineStep{
		{StepId: "step_1", Name: "DataIngestion", NodeType: "DATA_INGESTION", Description: "Fetch and normalize market data from Binance/CoinGecko", Order: 1},
		{StepId: "step_2", Name: "SignalResearch", NodeType: "SIGNAL_RESEARCH", Description: "Generate alpha signals from price, volume, and on-chain data", Order: 2},
		{StepId: "step_3", Name: "IntelligenceCoordination", NodeType: "STRATEGY", Description: "Coordinate signals across timeframes into a coherent view", Order: 3},
		{StepId: "step_4", Name: "DynamicWeights", NodeType: "RISK_MANAGEMENT", Description: "Compute dynamic portfolio weights based on conviction and risk", Order: 4},
		{StepId: "step_5", Name: "DebateGate", NodeType: "VERIFICATION", Description: "Adversarial debate gate — bull/bear case adjudication", Order: 5},
		{StepId: "step_6", Name: "WalkForward", NodeType: "VERIFICATION", Description: "Walk-forward backtest validation of proposed weights", Order: 6},
		{StepId: "step_7", Name: "Memory", NodeType: "MEMORY", Description: "Store episode context, update semantic memory", Order: 7},
		{StepId: "step_8", Name: "ImprovementEngine", NodeType: "IMPROVEMENT", Description: "TPE-driven hyperparameter optimisation across the pipeline", Order: 8},
		{StepId: "step_9", Name: "Ring3Adversarial", NodeType: "ADVERSARIAL", Description: "Final adversarial red-team before execution", Order: 9},
	}
	return &omegav1.Project{
		ProjectId:     "proj_victoria",
		Name:          "Victoria",
		Description:   "Autonomous crypto quantitative research and trading system",
		Status:        "active",
		Domain:        "crypto_quant",
		AutonomyLevel: "supervised",
		NodeIds:       []string{},
		PipelineConfig: steps,
		EvalConfig: &omegav1.EvalConfig{
			PrimaryMetrics: []string{"sharpe_ratio", "ic", "max_drawdown", "win_rate"},
			MetricTargets:  map[string]float64{"sharpe_ratio": 1.5, "ic": 0.05, "max_drawdown": -0.15},
			EvalFrequency:  "per_cycle",
		},
		ImprovementConfig: &omegav1.ImprovementConfig{
			TpeEnabled:          true,
			TpeTrials:           50,
			AdversarialEnabled:  true,
			AdversarialRounds:   3,
			WalkForwardEnabled:  true,
		},
		Metadata:  map[string]string{"color": "#00ff00"},
		CreatedAt: now,
		UpdatedAt: now,
	}
}
```

Note: add `omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"` and `"google.golang.org/protobuf/types/known/timestamppb"` to imports in main.go if not already present.

- [ ] **Step 3: Register ProjectService in mux (after dataPath registration, ~line 271)**

```go
projPath, projSvcHandler := omegav1connect.NewProjectServiceHandler(projectH, withHandlerOpts()...)
mux.Handle(projPath, projSvcHandler)
```

- [ ] **Step 4: Verify backend compiles and starts**

```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/wizardly-rubin
go build ./cmd/omega-api/...
```

Expected: exits 0.

- [ ] **Step 5: Commit Go backend**

```bash
git add internal/handler/project_handler.go cmd/omega-api/main.go
git commit -m "feat(backend): add ProjectHandler with in-memory store, seed Victoria project"
```

---

## Task 6: Add ProjectContext to frontend

**Files:**
- Create: `dashboard/src/context/ProjectContext.tsx`

- [ ] **Step 1: Write ProjectContext.tsx**

```tsx
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { projectClient } from "../client";
import type { Project } from "../gen/omega/v1/types_pb";

interface ProjectContextValue {
  projects: Project[];
  selectedProject: Project | null;
  setSelectedProject: (p: Project) => void;
  loading: boolean;
}

const ProjectContext = createContext<ProjectContextValue>({
  projects: [],
  selectedProject: null,
  setSelectedProject: () => {},
  loading: true,
});

export function ProjectProvider({ children }: { children: ReactNode }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    projectClient
      .listProjects({})
      .then((res) => {
        setProjects(res.projects);
        if (res.projects.length > 0) {
          setSelectedProject(res.projects[0]);
        }
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  return (
    <ProjectContext.Provider value={{ projects, selectedProject, setSelectedProject, loading }}>
      {children}
    </ProjectContext.Provider>
  );
}

export function useProject() {
  return useContext(ProjectContext);
}
```

---

## Task 7: Add projectClient to client.ts

**Files:**
- Modify: `dashboard/src/client.ts`

- [ ] **Step 1: Add projectClient export**

Current file:
```ts
import { createConnectTransport } from "@connectrpc/connect-web";
import { createClient } from "@connectrpc/connect";
import { OrchestratorService } from "./gen/omega/v1/omega_service_pb";

const baseUrl = import.meta.env.VITE_API_URL ?? "";

export const transport = createConnectTransport({ baseUrl });
export const client = createClient(OrchestratorService, transport);
```

Replace with:
```ts
import { createConnectTransport } from "@connectrpc/connect-web";
import { createClient } from "@connectrpc/connect";
import { OrchestratorService } from "./gen/omega/v1/omega_service_pb";
import { ProjectService } from "./gen/omega/v1/project_service_pb";

const baseUrl = import.meta.env.VITE_API_URL ?? "";

export const transport = createConnectTransport({ baseUrl });
export const client = createClient(OrchestratorService, transport);
export const projectClient = createClient(ProjectService, transport);
```

---

## Task 8: Update App.tsx — ProjectProvider + new routes

**Files:**
- Modify: `dashboard/src/App.tsx`

- [ ] **Step 1: Import ProjectProvider and Projects page**

Add to imports:
```tsx
import { ProjectProvider } from "./context/ProjectContext";
import Projects from "./pages/Projects";
```

- [ ] **Step 2: Wrap with ProjectProvider and add /projects route**

Replace:
```tsx
return (
  <BrowserRouter>
    <div className="flex min-h-screen bg-surface-900 text-gray-100">
      <Sidebar />
      ...
    </div>
  </BrowserRouter>
);
```

With:
```tsx
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
              <Route path="/victoria" element={<ErrorBoundary fallbackLabel="VictoriaDashboard"><VictoriaDashboard /></ErrorBoundary>} />
              <Route path="/victoria/portfolio" element={<ErrorBoundary fallbackLabel="VictoriaPortfolio"><VictoriaPortfolio /></ErrorBoundary>} />
              <Route path="/victoria/signals" element={<ErrorBoundary fallbackLabel="VictoriaSignals"><VictoriaSignals /></ErrorBoundary>} />
              <Route path="/victoria/trades" element={<ErrorBoundary fallbackLabel="VictoriaTrades"><VictoriaTrades /></ErrorBoundary>} />
              <Route path="/victoria/backtest" element={<ErrorBoundary fallbackLabel="VictoriaBacktest"><VictoriaBacktest /></ErrorBoundary>} />
            </Routes>
          </main>
        </div>
      </div>
    </ProjectProvider>
  </BrowserRouter>
);
```

Note: Victoria routes remain at `/victoria/*` for now — the sidebar section for the selected project links to these routes when Victoria is selected. Future projects will get their own route namespace.

---

## Task 9: Create Projects list page

**Files:**
- Create: `dashboard/src/pages/Projects.tsx`

- [ ] **Step 1: Write Projects.tsx**

```tsx
import { useProject } from "../context/ProjectContext";
import { Badge } from "../components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Layers, GitBranch, Server, ChevronRight } from "lucide-react";

const DOMAIN_LABELS: Record<string, string> = {
  crypto_quant: "Crypto Quant",
  macro_research: "Macro Research",
  options_arb: "Options Arb",
  custom: "Custom",
};

const STATUS_COLORS: Record<string, string> = {
  active: "bg-green-500/20 text-green-400 border-green-500/30",
  paused: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
  archived: "bg-gray-500/20 text-gray-400 border-gray-500/30",
};

export default function Projects() {
  const { projects, selectedProject, setSelectedProject, loading } = useProject();

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        Loading projects…
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Projects</h1>
          <p className="text-sm text-gray-400 mt-1">
            Configured instances driven by the Omega platform
          </p>
        </div>
      </div>

      {projects.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-64 text-gray-500 border border-dashed border-surface-600 rounded-xl">
          <Layers size={40} className="mb-3 opacity-30" />
          <p>No projects yet</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {projects.map((project) => (
            <Card
              key={project.projectId}
              className={`bg-surface-800 border cursor-pointer transition-all hover:border-indigo-500/50 ${
                selectedProject?.projectId === project.projectId
                  ? "border-indigo-500 ring-1 ring-indigo-500/30"
                  : "border-surface-600"
              }`}
              onClick={() => setSelectedProject(project)}
            >
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between gap-2">
                  <CardTitle className="text-white text-lg font-semibold">
                    {project.name}
                  </CardTitle>
                  <span
                    className={`text-xs px-2 py-0.5 rounded-full border font-medium ${
                      STATUS_COLORS[project.status] ?? STATUS_COLORS.archived
                    }`}
                  >
                    {project.status}
                  </span>
                </div>
                {project.description && (
                  <p className="text-sm text-gray-400 mt-1 line-clamp-2">
                    {project.description}
                  </p>
                )}
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex items-center gap-4 text-xs text-gray-400">
                  <span className="flex items-center gap-1.5">
                    <Server size={12} />
                    {project.nodeIds.length} nodes
                  </span>
                  <span className="flex items-center gap-1.5">
                    <GitBranch size={12} />
                    {project.pipelineConfig.length} steps
                  </span>
                  {project.domain && (
                    <Badge variant="outline" className="text-xs border-surface-500 text-gray-400">
                      {DOMAIN_LABELS[project.domain] ?? project.domain}
                    </Badge>
                  )}
                </div>

                {project.pipelineConfig.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-2">
                    {project.pipelineConfig.slice(0, 4).map((step) => (
                      <span
                        key={step.stepId}
                        className="text-xs bg-surface-700 text-gray-400 px-2 py-0.5 rounded"
                      >
                        {step.name}
                      </span>
                    ))}
                    {project.pipelineConfig.length > 4 && (
                      <span className="text-xs text-gray-600">
                        +{project.pipelineConfig.length - 4} more
                      </span>
                    )}
                  </div>
                )}

                <Button
                  variant="ghost"
                  size="sm"
                  className="w-full justify-between text-xs text-gray-400 hover:text-white mt-2"
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedProject(project);
                  }}
                >
                  {selectedProject?.projectId === project.projectId
                    ? "Currently selected"
                    : "Select project"}
                  <ChevronRight size={14} />
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
```

---

## Task 10: Update Sidebar — dynamic project selector + sections

**Files:**
- Modify: `dashboard/src/components/layout/Sidebar.tsx`

- [ ] **Step 1: Rewrite Sidebar.tsx**

```tsx
import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Server,
  GitBranch,
  BarChart2,
  AlertTriangle,
  Brain,
  TrendingUp,
  ShieldCheck,
  Swords,
  Target,
  Sword,
  History,
  Terminal,
  PieChart,
  Zap,
  List,
  FlaskConical,
  Layers,
  ChevronDown,
} from "lucide-react";
import { useState } from "react";
import { useProject } from "../../context/ProjectContext";
import type { Project } from "../../gen/omega/v1/types_pb";

const OMEGA_NAV = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/projects", icon: Layers, label: "Projects" },
  { to: "/nodes", icon: Server, label: "Nodes" },
  { to: "/traces", icon: GitBranch, label: "Traces" },
  { to: "/metrics", icon: BarChart2, label: "Metrics" },
  { to: "/issues", icon: AlertTriangle, label: "Issues" },
  { to: "/memory", icon: Brain, label: "Memory" },
  { to: "/convergence", icon: TrendingUp, label: "Convergence" },
  { to: "/alignment", icon: ShieldCheck, label: "Alignment" },
  { to: "/adversarial", icon: Swords, label: "Adversarial" },
  { to: "/goals", icon: Target, label: "Goals" },
  { to: "/challenges", icon: Sword, label: "Challenges" },
  { to: "/improvements", icon: History, label: "Improvements" },
];

// Victoria-specific nav. Future projects will declare their own views.
const VICTORIA_NAV = [
  { to: "/victoria", icon: Terminal, label: "Terminal" },
  { to: "/victoria/portfolio", icon: PieChart, label: "Portfolio" },
  { to: "/victoria/signals", icon: Zap, label: "Signals" },
  { to: "/victoria/trades", icon: List, label: "Trades" },
  { to: "/victoria/backtest", icon: FlaskConical, label: "Backtest" },
];

function projectNavItems(project: Project) {
  // Victoria uses its dedicated pages; future projects can extend this.
  if (project.projectId === "proj_victoria" || project.name === "Victoria") {
    return VICTORIA_NAV;
  }
  return [];
}

function ProjectSelector() {
  const { projects, selectedProject, setSelectedProject } = useProject();
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg text-sm font-medium bg-surface-700 text-white hover:bg-surface-600 transition-colors"
      >
        <span className="truncate">{selectedProject?.name ?? "Select project"}</span>
        <ChevronDown size={14} className={`shrink-0 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="absolute left-0 right-0 top-full mt-1 z-50 bg-surface-700 border border-surface-500 rounded-lg shadow-lg overflow-hidden">
          {projects.map((p) => (
            <button
              key={p.projectId}
              onClick={() => { setSelectedProject(p); setOpen(false); }}
              className={`w-full text-left px-3 py-2 text-sm hover:bg-surface-600 transition-colors ${
                selectedProject?.projectId === p.projectId ? "text-white font-semibold" : "text-gray-300"
              }`}
            >
              {p.name}
              <span className="ml-2 text-xs text-gray-500">{p.domain}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Sidebar() {
  const { selectedProject } = useProject();
  const projectNav = selectedProject ? projectNavItems(selectedProject) : [];
  const accentColor = selectedProject?.metadata?.color ?? "#00ff00";

  return (
    <aside className="w-56 min-h-screen bg-surface-800 border-r border-surface-600 flex flex-col py-6 px-3 gap-1 shrink-0 overflow-y-auto">
      <div className="px-3 mb-6">
        <span className="text-xl font-bold tracking-tight text-white">Ω Omega</span>
        <p className="text-xs text-gray-500 mt-0.5">Platform</p>
      </div>

      {/* OMEGA — global platform section */}
      <div className="px-3 mb-2">
        <span className="text-xs text-gray-600 uppercase tracking-widest font-semibold">
          Omega
        </span>
      </div>
      {OMEGA_NAV.map(({ to, icon: Icon, label }) => (
        <NavLink
          key={to}
          to={to}
          end={to === "/"}
          className={({ isActive }) =>
            `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
              isActive
                ? "bg-indigo-600 text-white"
                : "text-gray-400 hover:text-white hover:bg-surface-700"
            }`
          }
        >
          <Icon size={17} />
          {label}
        </NavLink>
      ))}

      {/* Divider */}
      <div className="border-t border-surface-600 my-3" />

      {/* Project selector */}
      <div className="px-3 mb-2">
        <span className="text-xs text-gray-600 uppercase tracking-widest font-semibold">
          Project
        </span>
      </div>
      <div className="mb-2">
        <ProjectSelector />
      </div>

      {/* Selected project nav */}
      {projectNav.length > 0 && (
        <>
          <div className="px-3 mb-1 mt-1">
            <span
              className="text-xs uppercase tracking-widest font-semibold"
              style={{ color: accentColor === "#00ff00" ? "#009900" : accentColor }}
            >
              {selectedProject?.name}
            </span>
          </div>
          {projectNav.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/victoria"}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                  isActive ? "text-black" : "hover:bg-surface-700"
                }`
              }
              style={({ isActive }) =>
                isActive
                  ? { backgroundColor: accentColor, color: "#000", textShadow: "none" }
                  : { color: accentColor === "#00ff00" ? "#009900" : accentColor }
              }
            >
              <Icon size={17} />
              {label}
            </NavLink>
          ))}
        </>
      )}
    </aside>
  );
}
```

---

## Task 11: Update Dashboard pipeline to read from selected project

**Files:**
- Modify: `dashboard/src/pages/Dashboard.tsx`

- [ ] **Step 1: Import useProject hook**

At the top of Dashboard.tsx, add:
```tsx
import { useProject } from "../context/ProjectContext";
```

- [ ] **Step 2: Replace hardcoded VICTORIA_PIPELINE constant with dynamic steps**

Find the existing hardcoded pipeline array (something like `VICTORIA_PIPELINE` or an array of `{ name, icon, ... }` step definitions near the top of the component). Replace the pipeline rendering section with:

```tsx
const { selectedProject } = useProject();

// Build pipeline display from selected project's pipeline_config.
const pipelineSteps = selectedProject?.pipelineConfig ?? [];
```

Then wherever the pipeline is rendered (the "VICTORIA PIPELINE" section), replace the hardcoded map with:

```tsx
{pipelineSteps.length > 0 ? (
  <div className="flex items-center gap-2 flex-wrap">
    {pipelineSteps
      .slice()
      .sort((a, b) => a.order - b.order)
      .map((step, idx) => (
        <div key={step.stepId} className="flex items-center gap-2">
          <div className="flex flex-col items-center gap-1">
            <div className="w-8 h-8 rounded-lg bg-surface-700 border border-surface-500 flex items-center justify-center text-xs font-mono text-gray-400">
              {step.order}
            </div>
            <span className="text-xs text-gray-400 max-w-[64px] text-center leading-tight">
              {step.name}
            </span>
          </div>
          {idx < pipelineSteps.length - 1 && (
            <div className="w-6 h-px bg-surface-600 mb-4" />
          )}
        </div>
      ))}
  </div>
) : (
  <p className="text-sm text-gray-500">No pipeline configured</p>
)}
```

Also update the section header from "VICTORIA PIPELINE" to use the selected project name:

```tsx
<h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
  {selectedProject?.name ?? "Project"} Pipeline
</h3>
```

- [ ] **Step 3: Verify TypeScript compiles with no errors**

```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/wizardly-rubin/dashboard
npm run build
```

Expected: Build succeeds with no TypeScript errors.

---

## Task 12: Final commit

- [ ] **Step 1: Stage all frontend changes**

```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/wizardly-rubin
git add dashboard/src/
```

- [ ] **Step 2: Verify no regressions**

```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/wizardly-rubin/dashboard
npm run build
```

Expected: exits 0.

- [ ] **Step 3: Commit**

```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/wizardly-rubin
git commit -m "feat(frontend): multi-project platform — ProjectContext, Projects page, dynamic sidebar, dynamic pipeline"
```

---

## Architecture Note

Omega is the **platform layer** — it owns orchestration, eval, feedback loops, and the global node registry. Projects are **configured instances** that declare:
- Which nodes from the global registry they use (`node_ids`)
- Their ordered execution pipeline (`pipeline_config`)
- Their domain and eval metrics (`domain`, `eval_config`)
- Their improvement settings (`improvement_config`)
- Their autonomy level (`autonomy_level`)

Omega drives the execution cycle **for** each project. Projects don't run themselves. This hierarchy is expressed in the sidebar (OMEGA → Projects → [Selected Project]) and in the proto model (Project references NodeCapability types from the global registry, not vice versa).
