package framework_test

import (
	"testing"

	"github.com/benebsworth/omega/internal/framework"
)

type Greeter interface {
	Greet() string
}

type englishGreeter struct{}

func (e *englishGreeter) Greet() string { return "hello" }

type spanishGreeter struct{}

func (s *spanishGreeter) Greet() string { return "hola" }

func TestServiceRegistry_RegisterAndGet(t *testing.T) {
	reg := framework.NewServiceRegistry()

	svc := &englishGreeter{}
	if err := framework.RegisterService[Greeter](reg, "greeter", svc); err != nil {
		t.Fatalf("RegisterService: %v", err)
	}

	got, err := framework.GetService[Greeter](reg, "greeter")
	if err != nil {
		t.Fatalf("GetService: %v", err)
	}
	if got.Greet() != "hello" {
		t.Fatalf("expected 'hello', got %q", got.Greet())
	}
}

func TestServiceRegistry_GetUnknownReturnsError(t *testing.T) {
	reg := framework.NewServiceRegistry()
	_, err := framework.GetService[Greeter](reg, "nonexistent")
	if err == nil {
		t.Fatal("expected error for unknown service")
	}
}

func TestServiceRegistry_GetTypeMismatchReturnsError(t *testing.T) {
	reg := framework.NewServiceRegistry()

	// Register as concrete type
	_ = framework.RegisterService[*englishGreeter](reg, "greeter", &englishGreeter{})

	// Try to get as different interface (Spanish greeter is not registered)
	_, err := framework.GetService[Greeter](reg, "other")
	if err == nil {
		t.Fatal("expected error for missing service")
	}
}

func TestServiceRegistry_DuplicateRegistrationReturnsError(t *testing.T) {
	reg := framework.NewServiceRegistry()
	_ = framework.RegisterService[Greeter](reg, "greeter", &englishGreeter{})
	if err := framework.RegisterService[Greeter](reg, "greeter", &spanishGreeter{}); err == nil {
		t.Fatal("expected error on duplicate service registration")
	}
}

func TestServiceRegistry_ListServices(t *testing.T) {
	reg := framework.NewServiceRegistry()
	_ = framework.RegisterService[Greeter](reg, "en", &englishGreeter{})
	_ = framework.RegisterService[Greeter](reg, "es", &spanishGreeter{})

	names := reg.ListServices()
	if len(names) != 2 {
		t.Fatalf("expected 2 services, got %d", len(names))
	}
}

func TestServiceRegistry_Unregister(t *testing.T) {
	reg := framework.NewServiceRegistry()
	_ = framework.RegisterService[Greeter](reg, "greeter", &englishGreeter{})

	if err := reg.Unregister("greeter"); err != nil {
		t.Fatalf("Unregister: %v", err)
	}

	_, err := framework.GetService[Greeter](reg, "greeter")
	if err == nil {
		t.Fatal("expected error after unregister")
	}
}

func TestServiceRegistry_UnregisterUnknownReturnsError(t *testing.T) {
	reg := framework.NewServiceRegistry()
	if err := reg.Unregister("nonexistent"); err == nil {
		t.Fatal("expected error unregistering unknown service")
	}
}
