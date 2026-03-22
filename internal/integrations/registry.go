package integrations

import (
	"context"
	"fmt"
	"sync"

	"golang.org/x/sync/errgroup"
)

// HealthCheckResult holds the result of a single connector health check.
type HealthCheckResult struct {
	Name  string
	Error error
}

// ConnectorRegistry manages registered connectors and provides lookup operations.
type ConnectorRegistry struct {
	mu         sync.RWMutex
	connectors map[string]Connector
}

// NewConnectorRegistry creates an empty registry.
func NewConnectorRegistry() *ConnectorRegistry {
	return &ConnectorRegistry{
		connectors: make(map[string]Connector),
	}
}

// Register adds a connector to the registry. Returns an error if the name is already taken.
func (r *ConnectorRegistry) Register(c Connector) error {
	r.mu.Lock()
	defer r.mu.Unlock()

	name := c.Name()
	if _, exists := r.connectors[name]; exists {
		return fmt.Errorf("connector %q already registered", name)
	}
	r.connectors[name] = c
	return nil
}

// Get returns a connector by name.
func (r *ConnectorRegistry) Get(name string) (Connector, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	c, ok := r.connectors[name]
	return c, ok
}

// GetByCategory returns all connectors matching the given category.
func (r *ConnectorRegistry) GetByCategory(cat Category) []Connector {
	r.mu.RLock()
	defer r.mu.RUnlock()

	var result []Connector
	for _, c := range r.connectors {
		if c.Category() == cat {
			result = append(result, c)
		}
	}
	return result
}

// List returns all registered connectors.
func (r *ConnectorRegistry) List() []Connector {
	r.mu.RLock()
	defer r.mu.RUnlock()

	result := make([]Connector, 0, len(r.connectors))
	for _, c := range r.connectors {
		result = append(result, c)
	}
	return result
}

// HealthCheckAll runs HealthCheck on all connectors in parallel and returns results.
// It never returns an error itself; individual connector errors are captured in results.
func (r *ConnectorRegistry) HealthCheckAll(ctx context.Context) []HealthCheckResult {
	r.mu.RLock()
	connectors := make([]Connector, 0, len(r.connectors))
	for _, c := range r.connectors {
		connectors = append(connectors, c)
	}
	r.mu.RUnlock()

	results := make([]HealthCheckResult, len(connectors))
	var eg errgroup.Group
	for i, c := range connectors {
		i, c := i, c
		eg.Go(func() error {
			results[i] = HealthCheckResult{
				Name:  c.Name(),
				Error: c.HealthCheck(ctx),
			}
			return nil
		})
	}
	_ = eg.Wait()
	return results
}
