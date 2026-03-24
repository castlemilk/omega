// Package projectseed loads project definitions from YAML files in the projects/
// directory and seeds them into a ProjectHandler at startup.
//
// YAML schema mirrors the Project proto message. Environment variable
// OMEGA_PROJECTS_DIR overrides the default search path ("./projects").
package projectseed

import (
	"fmt"
	"log"
	"os"
	"path/filepath"

	omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
	"google.golang.org/protobuf/types/known/timestamppb"
	"gopkg.in/yaml.v3"
)

// projectYAML is the YAML schema for a project definition file.
type projectYAML struct {
	ID            string            `yaml:"id"`
	Name          string            `yaml:"name"`
	Description   string            `yaml:"description"`
	Status        string            `yaml:"status"`
	Domain        string            `yaml:"domain"`
	AutonomyLevel string            `yaml:"autonomy_level"`
	NodeIDs       []string          `yaml:"node_ids"`
	Metadata      map[string]string `yaml:"metadata"`

	PipelineConfig []pipelineStepYAML `yaml:"pipeline_config"`
	EvalConfig     *evalConfigYAML    `yaml:"eval_config"`
	ImprovementCfg *improvementYAML   `yaml:"improvement_config"`
}

type pipelineStepYAML struct {
	StepID      string            `yaml:"step_id"`
	Name        string            `yaml:"name"`
	NodeType    string            `yaml:"node_type"`
	Description string            `yaml:"description"`
	Order       int32             `yaml:"order"`
	Config      map[string]string `yaml:"config"`
}

type evalConfigYAML struct {
	PrimaryMetrics []string           `yaml:"primary_metrics"`
	MetricTargets  map[string]float64 `yaml:"metric_targets"`
	EvalFrequency  string             `yaml:"eval_frequency"`
}

type improvementYAML struct {
	TPEEnabled         bool   `yaml:"tpe_enabled"`
	TPETrials          int32  `yaml:"tpe_trials"`
	AdversarialEnabled bool   `yaml:"adversarial_enabled"`
	AdversarialRounds  int32  `yaml:"adversarial_rounds"`
	WalkForwardEnabled bool   `yaml:"walk_forward_enabled"`
}

// Seeder accepts a project for registration.
type Seeder interface {
	SeedProject(p *omegav1.Project)
}

// LoadAndSeed reads all *.yaml files from dir (default: "./projects") and
// seeds each parsed project into s. Files that fail to parse are logged and
// skipped — they do not abort startup.
func LoadAndSeed(s Seeder, dir string) error {
	if dir == "" {
		dir = os.Getenv("OMEGA_PROJECTS_DIR")
	}
	if dir == "" {
		dir = "./projects"
	}

	entries, err := filepath.Glob(filepath.Join(dir, "*.yaml"))
	if err != nil {
		return fmt.Errorf("projectseed: glob %q: %w", dir, err)
	}
	if len(entries) == 0 {
		log.Printf("projectseed: no *.yaml files found in %s — no projects loaded", dir) //nolint:gosec
		return nil
	}

	for _, path := range entries {
		p, err := parseFile(path)
		if err != nil {
			log.Printf("projectseed: skipping %s: %v", path, err) //nolint:gosec
			continue
		}
		s.SeedProject(p)
		log.Printf("projectseed: loaded project %q (%s) from %s", p.ProjectId, p.Name, path) //nolint:gosec
	}
	return nil
}

func parseFile(path string) (*omegav1.Project, error) {
	data, err := os.ReadFile(path) //nolint:gosec // path comes from filepath.Glob on a trusted directory
	if err != nil {
		return nil, fmt.Errorf("read: %w", err)
	}

	var y projectYAML
	if err := yaml.Unmarshal(data, &y); err != nil {
		return nil, fmt.Errorf("yaml: %w", err)
	}
	if y.ID == "" {
		return nil, fmt.Errorf("missing required field: id")
	}
	if y.Name == "" {
		return nil, fmt.Errorf("missing required field: name")
	}

	now := timestamppb.Now()
	p := &omegav1.Project{
		ProjectId:     y.ID,
		Name:          y.Name,
		Description:   y.Description,
		Status:        coalesce(y.Status, "inactive"),
		Domain:        y.Domain,
		AutonomyLevel: y.AutonomyLevel,
		NodeIds:       y.NodeIDs,
		Metadata:      y.Metadata,
		CreatedAt:     now,
		UpdatedAt:     now,
	}

	for _, s := range y.PipelineConfig {
		p.PipelineConfig = append(p.PipelineConfig, &omegav1.PipelineStep{
			StepId:      s.StepID,
			Name:        s.Name,
			NodeType:    s.NodeType,
			Description: s.Description,
			Order:       s.Order,
			Config:      s.Config,
		})
	}

	if y.EvalConfig != nil {
		p.EvalConfig = &omegav1.EvalConfig{
			PrimaryMetrics: y.EvalConfig.PrimaryMetrics,
			MetricTargets:  y.EvalConfig.MetricTargets,
			EvalFrequency:  y.EvalConfig.EvalFrequency,
		}
	}

	if y.ImprovementCfg != nil {
		p.ImprovementConfig = &omegav1.ImprovementConfig{
			TpeEnabled:         y.ImprovementCfg.TPEEnabled,
			TpeTrials:          y.ImprovementCfg.TPETrials,
			AdversarialEnabled: y.ImprovementCfg.AdversarialEnabled,
			AdversarialRounds:  y.ImprovementCfg.AdversarialRounds,
			WalkForwardEnabled: y.ImprovementCfg.WalkForwardEnabled,
		}
	}

	return p, nil
}

func coalesce(s, fallback string) string {
	if s != "" {
		return s
	}
	return fallback
}
