// Package framework provides composability and extensibility primitives for the Omega platform.
// New domains, mechanisms, and layers plug in via the Plugin, Service, Capability, and Extension
// interfaces without modifying existing code.
package framework

import (
	"context"
	"fmt"
	"sync"
)

// ── Plugin interface ──────────────────────────────────────────────────────────

// Plugin is the contract every domain plugin must satisfy.
type Plugin interface {
	// Name returns the unique plugin identifier.
	Name() string
	// Version returns the semantic version string.
	Version() string
	// Dependencies returns names of plugins that must be initialised before this one.
	Dependencies() []string
	// Init is called once during startup in dependency order.
	Init(ctx context.Context, pc *PluginContext) error
	// Shutdown is called once during teardown in reverse dependency order.
	Shutdown(ctx context.Context) error
}

// ── PluginContext ─────────────────────────────────────────────────────────────

// PluginContext is passed to every plugin's Init method so plugins can access
// shared framework services without direct coupling.
type PluginContext struct {
	EventBus        *EventBus
	MetricsRegistry *MetricsRegistry
	ServiceRegistry *ServiceRegistry
	Config          ConfigProvider
}

// NewPluginContext constructs a PluginContext; any nil field is allowed (for tests).
func NewPluginContext(eb *EventBus, mr *MetricsRegistry, sr *ServiceRegistry, cfg ConfigProvider) *PluginContext {
	return &PluginContext{
		EventBus:        eb,
		MetricsRegistry: mr,
		ServiceRegistry: sr,
		Config:          cfg,
	}
}

// ── PluginRegistry ────────────────────────────────────────────────────────────

// PluginRegistry stores plugins and manages their lifecycle.
type PluginRegistry struct {
	mu       sync.RWMutex
	plugins  map[string]Plugin
	initOrder []string // topologically sorted, set after InitAll
}

// NewPluginRegistry returns an empty PluginRegistry.
func NewPluginRegistry() *PluginRegistry {
	return &PluginRegistry{plugins: make(map[string]Plugin)}
}

// Register adds a plugin. Returns an error if a plugin with the same name is already registered.
func (r *PluginRegistry) Register(p Plugin) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, exists := r.plugins[p.Name()]; exists {
		return fmt.Errorf("framework: plugin %q already registered", p.Name())
	}
	r.plugins[p.Name()] = p
	return nil
}

// Unregister removes a plugin by name. Returns an error if the name is unknown.
func (r *PluginRegistry) Unregister(name string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, exists := r.plugins[name]; !exists {
		return fmt.Errorf("framework: plugin %q not registered", name)
	}
	delete(r.plugins, name)
	return nil
}

// InitAll initialises all registered plugins in dependency order.
func (r *PluginRegistry) InitAll(ctx context.Context, pc *PluginContext) error {
	r.mu.Lock()
	defer r.mu.Unlock()

	order, err := topoSort(r.plugins)
	if err != nil {
		return fmt.Errorf("framework: dependency resolution: %w", err)
	}
	r.initOrder = order

	for _, name := range order {
		p := r.plugins[name]
		if err := p.Init(ctx, pc); err != nil {
			return fmt.Errorf("framework: plugin %q Init failed: %w", name, err)
		}
	}
	return nil
}

// ShutdownAll calls Shutdown on all initialised plugins in reverse init order.
func (r *PluginRegistry) ShutdownAll(ctx context.Context) error {
	r.mu.RLock()
	order := r.initOrder
	plugins := r.plugins
	r.mu.RUnlock()

	var errs []error
	for i := len(order) - 1; i >= 0; i-- {
		name := order[i]
		if p, ok := plugins[name]; ok {
			if err := p.Shutdown(ctx); err != nil {
				errs = append(errs, fmt.Errorf("plugin %q Shutdown: %w", name, err))
			}
		}
	}
	if len(errs) > 0 {
		return errs[0] // return first error; caller can inspect all if needed
	}
	return nil
}

// ── Topological sort (Kahn's algorithm) ──────────────────────────────────────

func topoSort(plugins map[string]Plugin) ([]string, error) {
	// Validate all declared dependencies exist.
	for name, p := range plugins {
		for _, dep := range p.Dependencies() {
			if _, ok := plugins[dep]; !ok {
				return nil, fmt.Errorf("plugin %q depends on unknown plugin %q", name, dep)
			}
		}
	}

	// Build in-degree map and adjacency list.
	inDegree := make(map[string]int, len(plugins))
	dependents := make(map[string][]string, len(plugins)) // dep → plugins that depend on dep

	for name := range plugins {
		if _, ok := inDegree[name]; !ok {
			inDegree[name] = 0
		}
	}
	for name, p := range plugins {
		for _, dep := range p.Dependencies() {
			inDegree[name]++
			dependents[dep] = append(dependents[dep], name)
		}
	}

	// Collect zero in-degree nodes as starting set.
	var queue []string
	for name, deg := range inDegree {
		if deg == 0 {
			queue = append(queue, name)
		}
	}

	// Sort queue for deterministic output.
	sortStrings(queue)

	var order []string
	for len(queue) > 0 {
		cur := queue[0]
		queue = queue[1:]
		order = append(order, cur)

		next := dependents[cur]
		sortStrings(next)
		for _, n := range next {
			inDegree[n]--
			if inDegree[n] == 0 {
				queue = append(queue, n)
				sortStrings(queue)
			}
		}
	}

	if len(order) != len(plugins) {
		return nil, fmt.Errorf("cyclic dependency detected among plugins")
	}
	return order, nil
}

func sortStrings(s []string) {
	// Simple insertion sort — plugin counts are small.
	for i := 1; i < len(s); i++ {
		for j := i; j > 0 && s[j] < s[j-1]; j-- {
			s[j], s[j-1] = s[j-1], s[j]
		}
	}
}

// ── EventBus ──────────────────────────────────────────────────────────────────

// Event is a named payload broadcast over the EventBus.
type Event struct {
	Topic   string
	Payload any
}

// EventHandler is a callback invoked when an event is published.
type EventHandler func(Event)

// EventBus is a simple in-process pub/sub bus.
type EventBus struct {
	mu          sync.RWMutex
	subscribers map[string]map[string]EventHandler // topic → id → handler
	nextID      uint64
}

// NewEventBus returns a ready-to-use EventBus.
func NewEventBus() *EventBus {
	return &EventBus{subscribers: make(map[string]map[string]EventHandler)}
}

// Subscribe registers a handler for a topic. Returns a subscription ID for later removal.
func (b *EventBus) Subscribe(topic string, h EventHandler) string {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.nextID++
	id := fmt.Sprintf("sub-%d", b.nextID)
	if b.subscribers[topic] == nil {
		b.subscribers[topic] = make(map[string]EventHandler)
	}
	b.subscribers[topic][id] = h
	return id
}

// Unsubscribe removes a subscription.
func (b *EventBus) Unsubscribe(topic, id string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	delete(b.subscribers[topic], id)
}

// Publish broadcasts an event to all topic subscribers synchronously.
func (b *EventBus) Publish(e Event) {
	b.mu.RLock()
	handlers := make([]EventHandler, 0, len(b.subscribers[e.Topic]))
	for _, h := range b.subscribers[e.Topic] {
		handlers = append(handlers, h)
	}
	b.mu.RUnlock()
	for _, h := range handlers {
		h(e)
	}
}

// ── MetricsRegistry ───────────────────────────────────────────────────────────

// MetricKind describes the type of a metric.
type MetricKind string

const (
	MetricCounter   MetricKind = "counter"
	MetricGauge     MetricKind = "gauge"
	MetricHistogram MetricKind = "histogram"
)

// MetricDescriptor describes a registered metric.
type MetricDescriptor struct {
	Name   string
	Kind   MetricKind
	Help   string
	Labels []string
}

// MetricsRegistry tracks metric descriptors. Actual recording is delegated to
// the MetricCollectionHook extension point (see extensions.go).
type MetricsRegistry struct {
	mu          sync.RWMutex
	descriptors map[string]MetricDescriptor
}

// NewMetricsRegistry returns an empty MetricsRegistry.
func NewMetricsRegistry() *MetricsRegistry {
	return &MetricsRegistry{descriptors: make(map[string]MetricDescriptor)}
}

// Register registers a metric descriptor.
func (r *MetricsRegistry) Register(d MetricDescriptor) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, ok := r.descriptors[d.Name]; ok {
		return fmt.Errorf("metrics: %q already registered", d.Name)
	}
	r.descriptors[d.Name] = d
	return nil
}

// Descriptor returns the descriptor for a named metric.
func (r *MetricsRegistry) Descriptor(name string) (MetricDescriptor, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	d, ok := r.descriptors[name]
	return d, ok
}

// ConfigProvider is the minimal read interface plugins need for config access.
// The full *Config satisfies this interface.
type ConfigProvider interface {
	GetString(key string) string
	GetInt(key string) int
	GetBool(key string) bool
	Sub(key string) ConfigProvider
}
