package framework_test

import (
	"context"
	"errors"
	"testing"

	"github.com/benebsworth/omega/internal/framework"
)

// --- stub plugins ---

type stubPlugin struct {
	name     string
	version  string
	deps     []string
	initErr  error
	shutErr  error
	initCalled bool
	shutCalled bool
}

func (p *stubPlugin) Name() string             { return p.name }
func (p *stubPlugin) Version() string          { return p.version }
func (p *stubPlugin) Dependencies() []string   { return p.deps }
func (p *stubPlugin) Init(_ context.Context, _ *framework.PluginContext) error {
	p.initCalled = true
	return p.initErr
}
func (p *stubPlugin) Shutdown(_ context.Context) error {
	p.shutCalled = true
	return p.shutErr
}

// --- tests ---

func TestPluginRegistry_RegisterAndInit(t *testing.T) {
	reg := framework.NewPluginRegistry()
	pc := framework.NewPluginContext(nil, nil, nil, nil)

	p := &stubPlugin{name: "alpha", version: "1.0.0"}
	if err := reg.Register(p); err != nil {
		t.Fatalf("Register: %v", err)
	}

	if err := reg.InitAll(context.Background(), pc); err != nil {
		t.Fatalf("InitAll: %v", err)
	}
	if !p.initCalled {
		t.Fatal("expected Init to be called")
	}
}

func TestPluginRegistry_DuplicateReturnsError(t *testing.T) {
	reg := framework.NewPluginRegistry()
	p := &stubPlugin{name: "alpha", version: "1.0.0"}
	_ = reg.Register(p)
	if err := reg.Register(p); err == nil {
		t.Fatal("expected error on duplicate registration")
	}
}

func TestPluginRegistry_DependencyOrder(t *testing.T) {
	reg := framework.NewPluginRegistry()
	pc := framework.NewPluginContext(nil, nil, nil, nil)

	alpha := &stubPlugin{name: "alpha", version: "1.0.0"}
	beta := &stubPlugin{name: "beta", version: "1.0.0", deps: []string{"alpha"}}
	gamma := &stubPlugin{name: "gamma", version: "1.0.0", deps: []string{"beta"}}

	// Register in reverse dependency order
	if err := reg.Register(gamma); err != nil {
		t.Fatal(err)
	}
	if err := reg.Register(alpha); err != nil {
		t.Fatal(err)
	}
	if err := reg.Register(beta); err != nil {
		t.Fatal(err)
	}

	if err := reg.InitAll(context.Background(), pc); err != nil {
		t.Fatalf("InitAll with deps: %v", err)
	}

	if !alpha.initCalled || !beta.initCalled || !gamma.initCalled {
		t.Fatal("all plugins should be initialised")
	}
}

func TestPluginRegistry_MissingDependencyError(t *testing.T) {
	reg := framework.NewPluginRegistry()
	pc := framework.NewPluginContext(nil, nil, nil, nil)

	beta := &stubPlugin{name: "beta", version: "1.0.0", deps: []string{"alpha"}}
	_ = reg.Register(beta)

	if err := reg.InitAll(context.Background(), pc); err == nil {
		t.Fatal("expected error for missing dependency 'alpha'")
	}
}

func TestPluginRegistry_CyclicDependencyError(t *testing.T) {
	reg := framework.NewPluginRegistry()
	pc := framework.NewPluginContext(nil, nil, nil, nil)

	a := &stubPlugin{name: "a", version: "1.0.0", deps: []string{"b"}}
	b := &stubPlugin{name: "b", version: "1.0.0", deps: []string{"a"}}
	_ = reg.Register(a)
	_ = reg.Register(b)

	if err := reg.InitAll(context.Background(), pc); err == nil {
		t.Fatal("expected error for cyclic dependency")
	}
}

func TestPluginRegistry_ShutdownReverseOrder(t *testing.T) {
	reg := framework.NewPluginRegistry()
	pc := framework.NewPluginContext(nil, nil, nil, nil)

	var shutOrder []string

	makeOrdered := func(name string, deps []string, record *[]string) framework.Plugin {
		return &trackingShutdownPlugin{
			name:    name,
			deps:    deps,
			record:  record,
		}
	}

	a := makeOrdered("a", nil, &shutOrder)
	b := makeOrdered("b", []string{"a"}, &shutOrder)

	_ = reg.Register(a)
	_ = reg.Register(b)
	_ = reg.InitAll(context.Background(), pc)

	if err := reg.ShutdownAll(context.Background()); err != nil {
		t.Fatalf("ShutdownAll: %v", err)
	}

	if len(shutOrder) != 2 {
		t.Fatalf("expected 2 shutdowns, got %d", len(shutOrder))
	}
	// b depends on a → b shuts down before a
	if shutOrder[0] != "b" || shutOrder[1] != "a" {
		t.Fatalf("expected shutdown order [b a], got %v", shutOrder)
	}
}

func TestPluginRegistry_InitErrorStops(t *testing.T) {
	reg := framework.NewPluginRegistry()
	pc := framework.NewPluginContext(nil, nil, nil, nil)

	bad := &stubPlugin{name: "bad", version: "1.0.0", initErr: errors.New("boom")}
	_ = reg.Register(bad)

	if err := reg.InitAll(context.Background(), pc); err == nil {
		t.Fatal("expected error when plugin Init fails")
	}
}

func TestPluginRegistry_Unregister(t *testing.T) {
	reg := framework.NewPluginRegistry()

	p := &stubPlugin{name: "alpha", version: "1.0.0"}
	_ = reg.Register(p)

	if err := reg.Unregister("alpha"); err != nil {
		t.Fatalf("Unregister: %v", err)
	}

	// re-registering should succeed now
	if err := reg.Register(p); err != nil {
		t.Fatalf("re-Register after Unregister: %v", err)
	}
}

func TestPluginRegistry_UnregisterUnknown(t *testing.T) {
	reg := framework.NewPluginRegistry()
	if err := reg.Unregister("nonexistent"); err == nil {
		t.Fatal("expected error unregistering unknown plugin")
	}
}

// trackingShutdownPlugin records shutdown call order.
type trackingShutdownPlugin struct {
	name   string
	deps   []string
	record *[]string
}

func (p *trackingShutdownPlugin) Name() string           { return p.name }
func (p *trackingShutdownPlugin) Version() string        { return "1.0.0" }
func (p *trackingShutdownPlugin) Dependencies() []string { return p.deps }
func (p *trackingShutdownPlugin) Init(_ context.Context, _ *framework.PluginContext) error {
	return nil
}
func (p *trackingShutdownPlugin) Shutdown(_ context.Context) error {
	*p.record = append(*p.record, p.name)
	return nil
}
