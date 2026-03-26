# Omega Dashboard — Design Review & Architecture Critique

**Date:** 2026-03-26
**Reviewer:** Ben (via automated design review)
**Scope:** Full UI/UX review of `web/dashboard/` prior to rebuild
**Status:** Pre-rebuild assessment

---

## 1. Executive Summary

The current Omega dashboard is a solid v1 that proves the data pipeline works end-to-end: Go Connect-RPC backend → SSE streaming → React frontend with live updates. The visual design is clean (dark theme, consistent color coding, good use of recharts). However, the dashboard is **single-project, single-concern** by design — it was built to monitor one Victoria instance and it shows. Before rebuilding, the following structural problems need addressing:

- **No multi-project support at all.** Victoria is hardcoded; there's no concept of Polymarket or future projects.
- **The overview page shows orchestration health, not trading outcomes.** PnL, positions, and signal quality — the things you actually care about — are absent.
- **Navigation is flat and shallow.** Six top-level pages with no drill-down routing means everything lives at the same depth. You can't link to a specific node, cycle, or trace.
- **Mock data is baked into components.** `OverviewPage` has hardcoded `cycleTrend` and `improvementTrend` arrays that never touch the API.
- **No URL routing.** The entire app is a `useState<Page>` toggle — you can't share a link, deep-link from alerts, or use browser back/forward.

The good news: the component quality is high, the API layer is clean, and the SSE plumbing works. This is a refactor, not a rewrite.

---

## 2. Current State Assessment

### 2.1 What Works Well

**Visual consistency.** The dark slate theme with emerald/amber/rose accent coding is applied uniformly. `StatusBadge` handles 16+ status variants cleanly. `MetricCard` is a solid reusable primitive.

**Data layer architecture.** The `useFetch` hook with 5-second polling and `useSSE` with auto-reconnect are the right patterns. The REST API client in `api.ts` is typed and minimal. SSE reconnect with 3-second backoff is sensible.

**Component isolation.** Each page fetches its own data. There's no global state spaghetti. Loading skeletons exist everywhere. Empty states are handled (though some are generic).

**Information density per page.** Individual pages like `AdversarialPage` (ring summary → heatmap → feed) and `ImprovementPage` (summary cards → ratio chart → per-node chart → timeline) have good progressive structure within themselves.

### 2.2 What Doesn't Work

**The overview page is nearly useless for a trader.** It shows: total nodes, active cycles, uptime, and autonomy percentage. None of these answer the question "am I making money?" or "is something broken that costs me money?" Cycle duration trend and improvement rate are secondary metrics at best. The event timeline is the most valuable widget and it's buried at the bottom.

**Hardcoded mock data.** `OverviewPage` generates `cycleTrend` and `improvementTrend` with `Math.random()` at import time. `NodesPage` has `SPARKLINE_DATA` that never reflects real node performance. `HealthPage.makeLatencyHistory` generates fake latency from a hash of the component name. These aren't placeholders — they're actively misleading.

**No URL routing or deep linking.** The entire app state is `useState<Page>('overview')`. Consequences: you can't bookmark the nodes page, can't link to a specific node or trace from a Slack alert, can't use browser back/forward, and the URL never changes. This is the single biggest UX debt.

**The sidebar navigation conflates concerns.** "Overview", "Nodes", "Cycles", "Adversarial", "Improvement", "Health" — these are all about the orchestration engine internals. Where are: Positions, Signals, PnL, Market Data, Strategies? The dashboard is an ops tool, not a trading tool.

**No project/environment context.** The API base URL is hardcoded to `/api/v1/dashboard`. The state store path is `/tmp/omega_victoria_state.db`. There's no project switcher, no environment indicator, and no way to add Polymarket without forking the entire frontend.

**Polling everything at 5 seconds is wasteful.** `useFetch` polls every 5s regardless of whether data changes. Health data might change every 30 seconds; node status might change every cycle. SSE already pushes events — the polling should be supplementary, not primary.

**No error boundaries or error display.** `useFetch` captures errors but no page displays them. If the API is down, you see loading skeletons forever.

---

## 3. Critique by Design Axis

### 3.1 Information Hierarchy

**Problem:** The most important information for a trading system operator is buried or absent.

**What should be front and center:**

1. **PnL (realized + unrealized)** — the single most important number. Should be the biggest element on screen.
2. **Active positions** — what's open right now, at what size, what's the current mark.
3. **Signal health** — are the data feeds alive? Are signals generating? Any staleness?
4. **System health** — is the orchestrator running, are cycles completing, any errors?

**What's currently front and center:** Node count, cycle count, uptime, autonomy percentage. These are infrastructure metrics, not business metrics.

**Recommendation:** The overview page should follow the Bloomberg Terminal mental model — the first thing you see is the "blotter" (positions + PnL), with system health as a secondary concern shown via status indicators rather than dedicated cards.

### 3.2 Multi-Project Support

**Current state:** Zero. The word "Victoria" doesn't even appear in the UI — there's simply no concept of projects.

**Proposed architecture:**

**URL structure:**
```
/                          → Project selector / portfolio overview
/:project/                 → Project dashboard (overview for that project)
/:project/nodes            → Nodes for that project
/:project/nodes/:nodeId    → Node detail
/:project/cycles           → Cycle history
/:project/cycles/:cycleId  → Cycle detail with trace waterfall
/:project/positions        → Active positions (trading projects)
/:project/signals          → Signal health and history
/:project/adversarial      → Adversarial monitoring
/:project/settings         → Project-specific config (brain config, etc.)
```

**Navigation model:**
- **Global header bar** with project switcher dropdown (like Vercel's project selector). Shows current project name + environment badge (live/paper/backtest).
- **Sidebar** is per-project navigation, same as now but scoped.
- **Portfolio view** at `/` shows a card per project with key metrics (PnL, cycle health, last activity) — like Datadog's service catalog or Railway's project grid.

**Data isolation:** The Go API already reads from a specific SQLite DB path. Multi-project support means parameterizing the DB path by project name and adding a `project` field to API routes: `/api/v1/projects/:project/dashboard/status`.

**Cross-project views:** Some views should aggregate across projects — total PnL, total costs, system-wide health. These live at the portfolio level (`/`), not within a project scope.

### 3.3 Extensibility

**Problem:** Adding a new node type, signal source, or project requires touching multiple hardcoded lists.

**What needs to be extensible:**

- **Node types** — The Nodes page should render any node with any capabilities, not assume a fixed set. Currently it does this well — `NodeRow` is generic.
- **Pages/views** — Adding a "Signals" or "Positions" page requires editing `App.tsx`'s nav array, adding a new page component, and there's no plugin or lazy-loading pattern.
- **Metric types** — `MetricCard` is generic, but the overview page hardcodes which 4 metrics to show. These should come from the API or a project-level config.
- **Status types** — `StatusBadge` handles 16+ statuses already, which is good. But the color mapping is in the component, not configurable.

**Recommendation:** Adopt a registry/config-driven approach:
- Pages register themselves (like a route manifest), not a hardcoded switch.
- The overview dashboard's widget grid should be configurable per project — Victoria shows PnL + positions; a pure orchestration project might show different widgets.
- Use React.lazy + Suspense for page-level code splitting.

### 3.4 Data Density vs. Clarity

**Current balance:** The dashboard is on the "too sparse" side. Each page shows 3-4 widgets with plenty of whitespace. This is fine for an ops dashboard but wrong for a trading dashboard.

**Trading dashboards need density.** A Bloomberg Terminal fits 8-12 data panels on screen simultaneously because traders need peripheral awareness — the PnL changing while you're looking at signal quality tells you something.

**Specific issues:**
- `MetricCard` is 5 lines of content in a card that takes ~25% of the row. The information-to-pixel ratio is low.
- Charts are 140px tall — barely enough to see a trend. For meaningful pattern recognition, 200-250px minimum.
- The event timeline (`max-h-80 overflow-y-auto`) is the most information-dense widget and it's capped at 320px. It should be larger or full-height in a sidebar.

**Recommendation:** Move toward a panel-based layout (like Grafana) where:
- The overview is a grid of resizable panels, each focused on one concern.
- Panels can be 1x1 (metric), 2x1 (sparkline + value), or 2x2 (full chart).
- Data density increases progressively — overview is medium density, drill-down pages are high density.

### 3.5 Navigation Structure

**Current:** 6 flat pages, no hierarchy, no drill-down.

**Problems:**
- Clicking a node in the Nodes table expands an inline row. You can't navigate to a node detail page with execution history, configuration, memory, etc.
- Clicking a cycle in Cycles shows inline details. You can't see which nodes ran, what traces were generated, or what issues were detected during that cycle.
- No breadcrumbs, no back navigation, no deep linking.

**Recommended page structure:**

```
Portfolio Overview (/)
├── Project Dashboard (/:project)
│   ├── Positions & PnL (/:project/positions)
│   ├── Signals (/:project/signals)
│   ├── Nodes (/:project/nodes)
│   │   └── Node Detail (/:project/nodes/:id)
│   │       ├── Execution History tab
│   │       ├── Configuration tab (brain config)
│   │       ├── Memory tab
│   │       └── Performance tab
│   ├── Cycles (/:project/cycles)
│   │   └── Cycle Detail (/:project/cycles/:id)
│   │       ├── Node execution breakdown
│   │       ├── Trace waterfall
│   │       └── Issues detected
│   ├── Traces (/:project/traces)
│   │   └── Trace Detail with span waterfall
│   ├── Issues (/:project/issues)
│   ├── Adversarial (/:project/adversarial)
│   ├── Improvement (/:project/improvement)
│   └── Settings (/:project/settings)
│       ├── Brain Configuration
│       └── Alert Rules
```

**Key changes from current:**
- Add Positions, Signals, and Settings pages.
- Make Nodes, Cycles, and Traces into master-detail with real URL routes.
- Add a Traces page (the plan has one but the current build doesn't).
- Group navigation into sections: "Trading" (Positions, Signals), "Operations" (Nodes, Cycles, Traces, Issues), "Safety" (Adversarial, Improvement), "Config" (Settings).

### 3.6 Real-Time Updates

**Current implementation:** SSE via `useSSE` hook pushes events to the `OverviewPage` event timeline. All other pages use 5-second polling via `useFetch`.

**Issues:**
- SSE events are only consumed on the Overview page. Other pages don't benefit from real-time updates.
- The SSE hook stores events in local state — if you navigate away and back, all events are lost.
- Polling at 5s for every page is aggressive for some data (health, improvements) and too slow for others (positions, prices).

**Recommendations:**
- **Lift SSE to app level.** Create a global `EventProvider` context that maintains the SSE connection and distributes events to all pages via React context. Events should persist across page navigation.
- **Use SSE to invalidate polling.** When a `cycle_complete` event arrives, invalidate/refetch the Cycles page data. When a `node_update` arrives, invalidate the Nodes page. This gives you instant updates without constant polling.
- **Tiered polling rates:** Positions/prices at 1-2s (or pure SSE push). Node status at 10s. Health at 30s. Improvements at 60s.
- **Visual update indicators:** When a value changes, briefly highlight it (a subtle flash or color transition). TradingView uses green/red flashes for price ticks. Avoid permanent blinking — it creates visual noise.
- **Stale data indicator:** If the SSE connection drops or data is older than 2x the expected refresh interval, show a "stale" badge on affected widgets.

### 3.7 Mobile Responsiveness

**Current state:** Minimal. The sidebar collapses (`w-16` vs `w-56`), and grid columns reduce on breakpoints (`grid-cols-2 lg:grid-cols-4`). But:
- The Nodes table doesn't transform into cards on mobile. A 7-column table is unreadable on a phone.
- Charts at 140px height are barely functional on desktop; on mobile they're noise.
- No bottom navigation — the sidebar pattern doesn't work well on phones.
- No consideration for touch targets (many buttons are `text-xs` with minimal padding).

**Recommendations:**
- **Mobile is monitoring mode.** On phone, show: system status (green/yellow/red), PnL number, position count, and last event. That's it. Everything else is a tap-to-expand.
- **Convert tables to card stacks.** The `NodeRow` pattern of expand/collapse is close — just make it card-based instead of table-row-based on mobile.
- **Bottom tab bar on mobile** with 4-5 key sections. The sidebar should hide entirely below `md` breakpoint, replaced by bottom tabs.
- **Touch targets minimum 44x44px** (Apple HIG). Current filter buttons (`px-3 py-1.5 text-xs`) are too small.
- **Defer charts on mobile.** Show the metric value with a trend arrow. Tap to see the chart in a sheet/modal.

---

## 4. Component Reusability Strategy

### 4.1 Current Reusable Components (Keep & Enhance)

| Component | Status | Enhancement Needed |
|-----------|--------|-------------------|
| `MetricCard` | Good primitive | Add sparkline variant, click-to-drill, loading error state |
| `StatusBadge` | Solid | Already handles 16+ variants — no changes needed |
| `EventTimeline` | Good | Add event grouping (per backlog R1), filtering, and persistence |

### 4.2 Components to Extract from Pages

| Source | New Component | Reuse Across |
|--------|--------------|-------------|
| `NodesPage.Sparkline` | `Sparkline` | Nodes, Health, Overview, Positions |
| `CyclesPage.CycleRow` | `CycleCard` | Cycles page, Cycle detail sidebar, Overview recent cycles |
| `AdversarialPage.AlertRow` | `AlertCard` | Adversarial page, Overview alerts panel, Node detail |
| `ImprovementPage` timeline items | `ImprovementEntry` | Improvement page, Node detail, Cycle detail |
| `HealthPage.HealthCard` | Already component | Reuse in Overview health summary |

### 4.3 New Components Needed

| Component | Purpose |
|-----------|---------|
| `ProjectSwitcher` | Dropdown in header to switch between Victoria, Polymarket, etc. |
| `PositionRow` / `PositionCard` | Display a single trading position with mark, PnL, size |
| `PnLDisplay` | Big number component with realized/unrealized breakdown and trend |
| `SignalHealthGrid` | Grid of signal sources with staleness, last value, health |
| `TraceWaterfall` | SVG waterfall for span trees (planned in original spec, not yet built) |
| `PageShell` | Standard page layout with title, breadcrumbs, actions bar |
| `DataPanel` | Configurable dashboard panel wrapper with title, loading, error, resize |
| `ErrorBanner` | Persistent banner for API errors, SSE disconnect, stale data |
| `EmptyState` | Standardized empty state with icon, message, and action CTA |

---

## 5. Multi-Project Architecture Proposal

### 5.1 Data Model

```
Project {
  id: string          // "victoria", "polymarket"
  name: string        // "Victoria"
  type: "trading" | "orchestration" | "hybrid"
  environment: "live" | "paper" | "backtest"
  dbPath: string      // resolved server-side
  apiBase: string     // /api/v1/projects/:id
  features: string[]  // ["positions", "signals", "adversarial", ...]
}
```

The `features` array controls which nav items appear. A pure orchestration project might not have "Positions" or "Signals." A trading project would have everything.

### 5.2 API Changes

Current: `/api/v1/dashboard/status`
Proposed: `/api/v1/projects/:project/status`

Add endpoints:
- `GET /api/v1/projects` — list all projects with summary health
- `GET /api/v1/projects/:project/positions` — active positions (trading projects)
- `GET /api/v1/projects/:project/signals` — signal source health and history
- `SSE /api/v1/projects/:project/events/stream` — project-scoped event stream

### 5.3 Frontend Routing

Replace `useState<Page>` with `react-router-dom` (or TanStack Router):

```
<Routes>
  <Route path="/" element={<PortfolioOverview />} />
  <Route path="/:project" element={<ProjectLayout />}>
    <Route index element={<ProjectDashboard />} />
    <Route path="positions" element={<PositionsPage />} />
    <Route path="signals" element={<SignalsPage />} />
    <Route path="nodes" element={<NodesPage />} />
    <Route path="nodes/:nodeId" element={<NodeDetailPage />} />
    <Route path="cycles" element={<CyclesPage />} />
    <Route path="cycles/:cycleId" element={<CycleDetailPage />} />
    <Route path="traces" element={<TracesPage />} />
    <Route path="traces/:traceId" element={<TraceDetailPage />} />
    <Route path="issues" element={<IssuesPage />} />
    <Route path="adversarial" element={<AdversarialPage />} />
    <Route path="improvement" element={<ImprovementPage />} />
    <Route path="settings" element={<SettingsPage />} />
  </Route>
</Routes>
```

`ProjectLayout` wraps the sidebar + header and provides project context to all child routes.

### 5.4 State Management

- **Project context:** `ProjectProvider` wraps `ProjectLayout`, provides `currentProject`, `projectConfig`, and project-scoped API client.
- **SSE context:** `EventProvider` at `ProjectLayout` level manages the SSE connection, scoped to current project. Connection tears down and reconnects on project switch.
- **Data fetching:** Continue with `useFetch` but add a `useProjectQuery(key, fetcher)` that automatically scopes to the current project and respects SSE invalidation.

---

## 6. Priority Ordering — What to Build First

### Phase 1: Foundation (Week 1)
_Must-have structural changes before any feature work._

1. **Add react-router-dom with URL routing.** Replace `useState<Page>` with proper routes. This unblocks deep linking, browser history, and the multi-project URL structure.
2. **Create `ProjectLayout` shell** with header (project name + status), sidebar (grouped nav), and content area.
3. **Lift SSE to context level.** Create `EventProvider` so all pages can react to real-time events.
4. **Add error boundary and error display.** Show API errors, SSE disconnection, and stale data warnings.
5. **Replace all mock/hardcoded data** with real API calls (cycleTrend, improvementTrend, SPARKLINE_DATA, makeLatencyHistory).

### Phase 2: Trading-First Overview (Week 2)
_Make the dashboard useful for its primary job: monitoring trading._

6. **Build the new Overview page** with: PnL card (big number, trend), active positions summary, signal health grid, system health indicator, recent events.
7. **Build Positions page** — table of open positions with size, entry, mark, unrealized PnL, time held.
8. **Build Signals page** — grid of signal sources with health, staleness, last value, and sparkline history.
9. **Add real sparklines** from API data to Nodes and Health pages, replacing the hardcoded arrays.

### Phase 3: Drill-Down & Detail (Week 3)
_Turn flat pages into master-detail with proper navigation._

10. **Node detail page** (`/:project/nodes/:id`) with tabs: execution history, brain config, performance metrics, memory.
11. **Cycle detail page** (`/:project/cycles/:id`) with node execution breakdown, mini trace waterfall, issues.
12. **Trace waterfall component** — SVG-based span tree visualization (as specified in original plan but not built).
13. **Issues page** with grouping by detector+field (backlog R2) and status filtering.

### Phase 4: Multi-Project (Week 4)
_Extend to support Polymarket and future projects._

14. **Portfolio overview page** at `/` — card grid of all projects with key metrics.
15. **Project switcher** in header with dropdown.
16. **Parameterize API layer** — all API calls scoped to current project from context.
17. **Feature flags per project** — conditionally show/hide nav items based on project type.

### Phase 5: Polish & Mobile (Week 5+)
_Quality of life and mobile access._

18. **Mobile responsive layout** — bottom tabs, card stacks, deferred charts.
19. **Keyboard shortcuts** — `g` then `n` for nodes, `g` then `c` for cycles (Vim-style navigation).
20. **Event grouping** (backlog R1) — collapse identical events in timeline.
21. **Configurable dashboard panels** — allow reordering/resizing overview widgets.
22. **Dark/light theme toggle** (low priority, but easy with Tailwind's dark mode classes).

---

## 7. Extensibility Guidelines

### Adding a New Project

1. Register the project in the Go backend (project config with DB path, features list).
2. No frontend code changes needed — `PortfolioOverview` lists all projects from API, `ProjectLayout` reads features from project config to build nav.

### Adding a New Node Type

1. No changes needed if the node follows the existing `Node` interface (name, status, autonomy, performance metrics).
2. If the node has custom metrics, they should be surfaced through the existing `performance.metrics` map — the UI should render all metric keys generically.

### Adding a New Page/View

1. Create the page component in `src/pages/`.
2. Add a route entry in the router config.
3. Add a nav entry in the sidebar config (this should be a data structure, not JSX).
4. If the page should only appear for certain project types, add it to the feature flag list.

### Adding a New Signal Source

1. The Signals page should render any signal source returned by the API — no hardcoded source list.
2. Each signal source provides: name, type, health status, last value, last update time, staleness threshold.
3. New sources appear automatically when the backend starts reporting them.

### Adding a New Metric to Overview

1. Overview widgets should be driven by a project-level widget config (either from API or a local config file).
2. Each widget specifies: type (metric, chart, table, timeline), data source (API endpoint), refresh strategy (SSE-driven vs polling interval), and size (1x1, 2x1, etc.).
3. Adding a metric means adding an entry to the config — no component code changes for standard metric types.

---

## 8. Technical Debt to Address During Rebuild

| Item | Current State | Fix |
|------|--------------|-----|
| No router | `useState<Page>` | `react-router-dom` v6 or TanStack Router |
| Mock data in components | Hardcoded arrays | Remove entirely; use API data only |
| No error handling UI | Errors silently swallowed | Add `ErrorBanner`, per-widget error states |
| No TypeScript strict mode | Likely lenient config | Enable `strict: true` in tsconfig |
| Polling-only data fetching | 5s polling for everything | SSE-driven invalidation + tiered polling |
| No code splitting | All pages in one bundle | `React.lazy` + `Suspense` per page |
| No test coverage | Zero tests visible | Add Vitest + Testing Library for critical components |
| Inline styles in components | Mixed Tailwind + inline style objects | Standardize on Tailwind-only where possible |
| No accessibility | No ARIA labels, no keyboard nav | Add aria-label to interactive elements, keyboard navigation |
| `useFetch` shadow naming | Hook variable `fetch` shadows global | Rename to `doFetch` or `load` |

---

## 9. Open Questions for Ben

1. **What's the primary persona?** Is the dashboard primarily for you (the developer/operator) or will others use it? This affects complexity tolerance.
2. **Polymarket timeline?** When does multi-project support actually need to work? If it's weeks away, we can build the foundation now and defer the portfolio view.
3. **Position data availability.** Do the Victoria/Polymarket backends already expose position and PnL data, or does the API need to be built too?
4. **Backtest mode.** Should the dashboard support viewing historical/backtest runs alongside live data? This significantly changes the data model.
5. **Alert routing.** Should the dashboard be the alerting system (push notifications, sound alerts on critical events) or is that handled externally (PagerDuty, Slack)?
