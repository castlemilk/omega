package framework

import (
	"fmt"
	"sync"
)

// ServiceRegistry is a thread-safe service locator.
// Services are stored as any and retrieved with type assertions via the
// package-level generic helpers RegisterService and GetService.
type ServiceRegistry struct {
	mu       sync.RWMutex
	services map[string]any
}

// NewServiceRegistry returns an empty ServiceRegistry.
func NewServiceRegistry() *ServiceRegistry {
	return &ServiceRegistry{services: make(map[string]any)}
}

// RegisterService stores impl under name with type safety provided by the
// generic parameter T. Returns an error if the name is already taken.
func RegisterService[T any](reg *ServiceRegistry, name string, impl T) error {
	reg.mu.Lock()
	defer reg.mu.Unlock()
	if _, exists := reg.services[name]; exists {
		return fmt.Errorf("service_registry: service %q already registered", name)
	}
	reg.services[name] = impl
	return nil
}

// GetService retrieves a service by name and asserts it to type T.
// Returns an error if the name is unknown or the stored value is not assignable to T.
func GetService[T any](reg *ServiceRegistry, name string) (T, error) {
	reg.mu.RLock()
	raw, ok := reg.services[name]
	reg.mu.RUnlock()

	var zero T
	if !ok {
		return zero, fmt.Errorf("service_registry: service %q not found", name)
	}
	typed, ok := raw.(T)
	if !ok {
		return zero, fmt.Errorf("service_registry: service %q has type %T, cannot assert to %T", name, raw, zero)
	}
	return typed, nil
}

// Unregister removes a service by name. Returns an error if the name is unknown.
func (r *ServiceRegistry) Unregister(name string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, ok := r.services[name]; !ok {
		return fmt.Errorf("service_registry: service %q not registered", name)
	}
	delete(r.services, name)
	return nil
}

// ListServices returns all registered service names.
func (r *ServiceRegistry) ListServices() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()
	names := make([]string, 0, len(r.services))
	for name := range r.services {
		names = append(names, name)
	}
	return names
}
