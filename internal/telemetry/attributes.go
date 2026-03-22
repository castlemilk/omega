// Package telemetry is the foundational observability layer for Omega.
// All nodes, handlers, and framework components import this package to get
// consistent tracing, metrics, and logging without extra configuration.
package telemetry

import "go.opentelemetry.io/otel/attribute"

// Standard Omega attribute keys used across all telemetry signals.
// Every span, metric data point, and log record should carry the applicable
// subset of these keys so that signals can be correlated in a backend.
var (
	// Node identity
	AttrNodeName = attribute.Key("omega.node.name")
	AttrNodeType = attribute.Key("omega.node.type")
	AttrNodeID   = attribute.Key("omega.node.id")

	// Execution context
	AttrCycleID  = attribute.Key("omega.cycle.id")
	AttrAction   = attribute.Key("omega.action")
	AttrDepth    = attribute.Key("omega.depth")

	// Autonomy & safety
	AttrAutonomyLevel = attribute.Key("omega.autonomy.level")
	AttrRing          = attribute.Key("omega.ring")

	// RPC
	AttrRPCMethod  = attribute.Key("omega.rpc.method")
	AttrRPCService = attribute.Key("omega.rpc.service")
	AttrRPCStatus  = attribute.Key("omega.rpc.status")

	// Memory
	AttrMemoryNamespace = attribute.Key("omega.memory.namespace")
	AttrMemoryEventType = attribute.Key("omega.memory.event_type")
	AttrMemoryOperation = attribute.Key("omega.memory.operation")

	// Signal generation (Victoria)
	AttrSignalTicker    = attribute.Key("omega.signal.ticker")
	AttrSignalIndicator = attribute.Key("omega.signal.indicator")
	AttrSignalVersion   = attribute.Key("omega.signal.version")

	// Improvement
	AttrImprovementOutcome = attribute.Key("omega.improvement.outcome")

	// Error detail
	AttrErrorKind = attribute.Key("omega.error.kind")
)

// Span names — use these constants in StartSpan calls to ensure consistency.
const (
	SpanOrchestratorCycle    = "omega.orchestrator.cycle"
	SpanNodeExecution        = "omega.node.execute"
	SpanMemoryStore          = "omega.memory.store"
	SpanMemoryQuery          = "omega.memory.query"
	SpanMemoryConsolidate    = "omega.memory.consolidate"
	SpanRPCHandler           = "omega.rpc.handler"
	SpanSignalGeneration     = "omega.signal.generate"
	SpanWriteQueueEnqueue    = "omega.memory.write_queue.enqueue"
	SpanWriteQueueFlush      = "omega.memory.write_queue.flush"
	SpanMiddlewareChain      = "omega.middleware.chain"
)

// Meter/instrument names.
const (
	MetricHandlerRequestDuration  = "omega.handler.request.duration"
	MetricHandlerRequestCount     = "omega.handler.request.count"
	MetricHandlerErrorCount       = "omega.handler.error.count"
	MetricHandlerActiveRequests   = "omega.handler.active_requests"

	MetricWriteQueueDepth         = "omega.memory.write_queue.depth"
	MetricWriteLatency            = "omega.memory.write.latency"
	MetricConsolidationLatency    = "omega.memory.consolidation.latency"
	MetricCacheHits               = "omega.memory.cache.hits"
	MetricCacheMisses             = "omega.memory.cache.misses"
	MetricContradictions          = "omega.memory.contradictions"

	MetricSignalICPerBar          = "omega.signal.ic_per_bar"
	MetricSignalGenerationLatency = "omega.signal.generation.latency"
	MetricTPETrialScore           = "omega.signal.tpe.trial_score"

	MetricNodeExecutionLatency    = "omega.node.execution.latency"
	MetricCycleDuration           = "omega.orchestrator.cycle.duration"
)
