// Package core — config_hot_reload.go
//
// ConfigHotReloader watches a YAML config file for changes, diffs the node
// configuration, and applies changes through the ReconfigEngine with a safety
// gate and automatic rollback on failure.
//
// YAML schema example:
//
//	nodes:
//	  - node_id: alpha
//	    node_type: quant
//	    strategy_id: momentum
//	    params:
//	      window: "20"
//	    autonomy_thresholds:
//	      min_cycles_for_promotion: 10
//	      min_sharpe_for_promotion: 0.5
//	      max_drawdown_for_demotion: 0.15
//	      confidence_floor: 0.6
package core

import (
	"context"
	"fmt"
	"log/slog"
	"sync"

	"github.com/fsnotify/fsnotify"
	"github.com/spf13/viper"

	"github.com/benebsworth/omega/internal/framework"
)

// ---------------------------------------------------------------------------
// Event topics
// ---------------------------------------------------------------------------

const (
	// TopicConfirmationRequired is emitted when a config change would affect
	// more than 50 % of tracked nodes and requires manual confirmation.
	TopicConfirmationRequired = "reconfig.confirmation_required"

	// TopicConfigApplied is emitted after a successful config reload.
	TopicConfigApplied = "reconfig.config_applied"

	// TopicConfigRollback is emitted when a reload fails and the previous
	// configuration has been restored.
	TopicConfigRollback = "reconfig.config_rollback"
)

// ---------------------------------------------------------------------------
// HotReloadConfig — in-memory representation of the YAML file
// ---------------------------------------------------------------------------

// HotReloadNodeConfig is the YAML representation of a single node.
type HotReloadNodeConfig struct {
	NodeID             string                 `mapstructure:"node_id"`
	NodeType           string                 `mapstructure:"node_type"`
	StrategyID         string                 `mapstructure:"strategy_id"`
	Params             map[string]interface{} `mapstructure:"params"`
	AutonomyThresholds struct {
		MinCyclesForPromotion  int64   `mapstructure:"min_cycles_for_promotion"`
		MinSharpeForPromotion  float64 `mapstructure:"min_sharpe_for_promotion"`
		MaxDrawdownForDemotion float64 `mapstructure:"max_drawdown_for_demotion"`
		ConfidenceFloor        float64 `mapstructure:"confidence_floor"`
	} `mapstructure:"autonomy_thresholds"`
}

// HotReloadFileConfig is the top-level structure of the watched YAML file.
type HotReloadFileConfig struct {
	Nodes []HotReloadNodeConfig `mapstructure:"nodes"`
}

// ---------------------------------------------------------------------------
// ConfigHotReloader
// ---------------------------------------------------------------------------

// ConfigHotReloader watches a YAML config file and applies incremental changes
// to the system via a ReconfigEngine.
type ConfigHotReloader struct {
	mu     sync.Mutex
	path   string
	engine *ReconfigEngine
	bus    *framework.EventBus
	logger *slog.Logger

	prev HotReloadFileConfig // last successfully applied config
}

// NewConfigHotReloader creates a ConfigHotReloader.
// bus and logger may be nil.
func NewConfigHotReloader(
	path string,
	engine *ReconfigEngine,
	bus *framework.EventBus,
	logger *slog.Logger,
) *ConfigHotReloader {
	if logger == nil {
		logger = slog.Default()
	}
	return &ConfigHotReloader{
		path:   path,
		engine: engine,
		bus:    bus,
		logger: logger,
	}
}

// WatchConfig loads the config at path immediately, then blocks watching for
// changes until ctx is cancelled. Each detected change triggers a diff-and-apply
// cycle with safety gate and rollback on failure.
func (r *ConfigHotReloader) WatchConfig(ctx context.Context) error {
	initial, err := r.loadConfig(r.path)
	if err != nil {
		return fmt.Errorf("hot_reload: initial load failed: %w", err)
	}

	r.mu.Lock()
	r.prev = initial
	r.mu.Unlock()

	v := viper.New()
	v.SetConfigFile(r.path)
	if err := v.ReadInConfig(); err != nil {
		return fmt.Errorf("hot_reload: viper read failed: %w", err)
	}

	v.WatchConfig()
	v.OnConfigChange(func(e fsnotify.Event) {
		r.logger.Info("hot_reload: config file changed", "file", e.Name, "op", e.Op.String())
		r.handleChange(v)
	})

	r.logger.Info("hot_reload: watching config", "path", r.path)
	<-ctx.Done()
	return ctx.Err()
}

// ApplyConfig performs a one-shot load and apply of the config file without
// starting a file watcher. Useful for initial bootstrap and tests.
func (r *ConfigHotReloader) ApplyConfig(path string) error {
	next, err := r.loadConfig(path)
	if err != nil {
		return fmt.Errorf("hot_reload: load failed: %w", err)
	}

	r.mu.Lock()
	prev := r.prev
	r.mu.Unlock()

	if err := r.applyDiff(prev, next); err != nil {
		return err
	}

	r.mu.Lock()
	r.prev = next
	r.mu.Unlock()
	return nil
}

// ---------------------------------------------------------------------------
// internal: change handler
// ---------------------------------------------------------------------------

func (r *ConfigHotReloader) handleChange(v *viper.Viper) {
	var next HotReloadFileConfig
	if err := v.Unmarshal(&next); err != nil {
		r.logger.Error("hot_reload: unmarshal failed", "err", err)
		return
	}

	r.mu.Lock()
	prev := r.prev
	r.mu.Unlock()

	if err := r.applyDiff(prev, next); err != nil {
		r.logger.Error("hot_reload: apply failed, rolling back", "err", err)
		r.rollback(prev)
		return
	}

	r.mu.Lock()
	r.prev = next
	r.mu.Unlock()

	r.logger.Info("hot_reload: config applied successfully")
	r.publish(TopicConfigApplied, map[string]interface{}{
		"nodes_after": len(next.Nodes),
	})
}

// applyDiff computes the diff between prev and next and applies it via the
// ReconfigEngine. Safety gate: if >50 % of current tracked nodes would be
// affected, a ConfirmationRequiredEvent is emitted and the apply is aborted.
func (r *ConfigHotReloader) applyDiff(prev, next HotReloadFileConfig) error {
	prevMap := make(map[string]HotReloadNodeConfig, len(prev.Nodes))
	nextMap := make(map[string]HotReloadNodeConfig, len(next.Nodes))

	for _, n := range prev.Nodes {
		prevMap[n.NodeID] = n
	}
	for _, n := range next.Nodes {
		nextMap[n.NodeID] = n
	}

	// Compute affected set.
	affected := make(map[string]struct{})
	for id := range nextMap {
		if _, exists := prevMap[id]; !exists {
			affected[id] = struct{}{} // new node
		}
	}
	for id := range prevMap {
		if _, exists := nextMap[id]; !exists {
			affected[id] = struct{}{} // removed node
		}
	}
	for id, n := range nextMap {
		if p, ok := prevMap[id]; ok && hotConfigChanged(p, n) {
			affected[id] = struct{}{} // modified node
		}
	}

	// Safety gate: require confirmation if > 50% of reloader-managed nodes are affected.
	// We use len(prevMap) as the baseline so the gate reflects the reloader's own view
	// of the world, not the total orchestrator node count (which may include nodes added
	// outside this reloader).
	total := len(prevMap)
	if total > 0 && len(affected) > total/2 {
		r.publish(TopicConfirmationRequired, map[string]interface{}{
			"affected_count": len(affected),
			"total_nodes":    total,
		})
		return fmt.Errorf("hot_reload: safety gate triggered: %d/%d nodes affected, manual confirmation required",
			len(affected), total)
	}

	// Apply: removals first, then additions, then updates.
	for id := range prevMap {
		if _, inNext := nextMap[id]; !inNext {
			if err := r.engine.RemoveNode(id); err != nil {
				return fmt.Errorf("hot_reload: remove %q: %w", id, err)
			}
		}
	}
	for id, n := range nextMap {
		if _, inPrev := prevMap[id]; !inPrev {
			cfg := hotNodeConfigToNodeConfig(n)
			if err := r.engine.AddNode(cfg); err != nil {
				return fmt.Errorf("hot_reload: add %q: %w", id, err)
			}
		}
	}
	for id, n := range nextMap {
		if p, ok := prevMap[id]; ok && hotConfigChanged(p, n) {
			// Strategy swap
			if n.StrategyID != p.StrategyID {
				if err := r.engine.SwapStrategy(id, n.StrategyID); err != nil {
					return fmt.Errorf("hot_reload: swap strategy %q: %w", id, err)
				}
			}
			// Param update
			if !mapsEqual(p.Params, n.Params) {
				if err := r.engine.UpdateNodeConfig(id, n.Params); err != nil {
					return fmt.Errorf("hot_reload: update params %q: %w", id, err)
				}
			}
			// Autonomy thresholds
			newT := n.AutonomyThresholds
			oldT := p.AutonomyThresholds
			if newT != oldT {
				thresholds := AutonomyThresholds{
					MinCyclesForPromotion:  newT.MinCyclesForPromotion,
					MinSharpeForPromotion:  newT.MinSharpeForPromotion,
					MaxDrawdownForDemotion: newT.MaxDrawdownForDemotion,
					ConfidenceFloor:        newT.ConfidenceFloor,
				}
				if err := r.engine.ReconfigureAutonomy(id, thresholds); err != nil {
					return fmt.Errorf("hot_reload: reconfigure autonomy %q: %w", id, err)
				}
			}
		}
	}

	return nil
}

// rollback re-applies the previous config from scratch by reversing the diff.
func (r *ConfigHotReloader) rollback(prev HotReloadFileConfig) {
	r.logger.Warn("hot_reload: rolling back to previous config")

	// Snapshot current engine nodes and remove any that are not in prev.
	current := r.engine.Nodes()
	prevMap := make(map[string]HotReloadNodeConfig, len(prev.Nodes))
	for _, n := range prev.Nodes {
		prevMap[n.NodeID] = n
	}

	for id := range current {
		if _, inPrev := prevMap[id]; !inPrev {
			if err := r.engine.RemoveNode(id); err != nil {
				r.logger.Error("hot_reload: rollback remove failed", "node_id", id, "err", err)
			}
		}
	}

	// Re-add nodes that should exist according to prev but were just removed.
	for _, n := range prev.Nodes {
		if _, exists := r.engine.Nodes()[n.NodeID]; !exists {
			cfg := hotNodeConfigToNodeConfig(n)
			if err := r.engine.AddNode(cfg); err != nil {
				r.logger.Error("hot_reload: rollback re-add failed", "node_id", n.NodeID, "err", err)
			}
		}
	}

	r.publish(TopicConfigRollback, map[string]interface{}{
		"rolled_back_to": len(prev.Nodes),
	})
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

func (r *ConfigHotReloader) loadConfig(path string) (HotReloadFileConfig, error) {
	v := viper.New()
	v.SetConfigFile(path)
	if err := v.ReadInConfig(); err != nil {
		return HotReloadFileConfig{}, err
	}
	var cfg HotReloadFileConfig
	if err := v.Unmarshal(&cfg); err != nil {
		return HotReloadFileConfig{}, err
	}
	return cfg, nil
}

func (r *ConfigHotReloader) publish(topic string, details map[string]interface{}) {
	if r.bus == nil {
		return
	}
	r.bus.Publish(framework.Event{
		Topic:   topic,
		Payload: details,
	})
}

func hotConfigChanged(a, b HotReloadNodeConfig) bool {
	if a.StrategyID != b.StrategyID {
		return true
	}
	if a.AutonomyThresholds != b.AutonomyThresholds {
		return true
	}
	return !mapsEqual(a.Params, b.Params)
}

func mapsEqual(a, b map[string]interface{}) bool {
	if len(a) != len(b) {
		return false
	}
	for k, va := range a {
		vb, ok := b[k]
		if !ok {
			return false
		}
		if fmt.Sprintf("%v", va) != fmt.Sprintf("%v", vb) {
			return false
		}
	}
	return true
}

func hotNodeConfigToNodeConfig(h HotReloadNodeConfig) NodeConfig {
	t := h.AutonomyThresholds
	return NodeConfig{
		NodeID:     h.NodeID,
		NodeType:   h.NodeType,
		StrategyID: h.StrategyID,
		Params:     h.Params,
		AutonomyThresholds: AutonomyThresholds{
			MinCyclesForPromotion:  t.MinCyclesForPromotion,
			MinSharpeForPromotion:  t.MinSharpeForPromotion,
			MaxDrawdownForDemotion: t.MaxDrawdownForDemotion,
			ConfidenceFloor:        t.ConfidenceFloor,
		},
	}
}
