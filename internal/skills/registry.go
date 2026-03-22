package skills

import (
	"fmt"
	"path/filepath"
	"sync"
)

// SkillRegistry manages the lifecycle of locally installed skills.
type SkillRegistry struct {
	mu       sync.RWMutex
	skills   map[string]Skill
	storeDir string
}

// NewSkillRegistry creates a registry that extracts skill archives into storeDir.
func NewSkillRegistry(storeDir string) *SkillRegistry {
	return &SkillRegistry{
		skills:   make(map[string]Skill),
		storeDir: storeDir,
	}
}

// Install unpackages the skill archive at archivePath and registers the skill.
func (r *SkillRegistry) Install(archivePath string) error {
	r.mu.Lock()
	defer r.mu.Unlock()

	manifest, err := ReadManifest(archivePath)
	if err != nil {
		return fmt.Errorf("registry: read manifest: %w", err)
	}

	skillDir := filepath.Join(r.storeDir, manifest.Name)
	skill, err := Unpackage(archivePath, skillDir)
	if err != nil {
		return fmt.Errorf("registry: unpackage: %w", err)
	}

	r.skills[skill.Name] = *skill
	return nil
}

// Uninstall removes a skill from the registry by name.
func (r *SkillRegistry) Uninstall(name string) error {
	r.mu.Lock()
	defer r.mu.Unlock()

	if _, ok := r.skills[name]; !ok {
		return fmt.Errorf("registry: skill %q is not installed", name)
	}
	delete(r.skills, name)
	return nil
}

// List returns a snapshot of all installed skills.
func (r *SkillRegistry) List() []Skill {
	r.mu.RLock()
	defer r.mu.RUnlock()

	out := make([]Skill, 0, len(r.skills))
	for _, s := range r.skills {
		out = append(out, s)
	}
	return out
}

// Get returns the installed skill with the given name.
func (r *SkillRegistry) Get(name string) (*Skill, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	s, ok := r.skills[name]
	if !ok {
		return nil, fmt.Errorf("registry: skill %q not found", name)
	}
	return &s, nil
}

// Resolve performs a topological sort over the given dependency names, returning
// them in install order. Returns an error if a dependency is missing or if a
// cycle is detected.
func (r *SkillRegistry) Resolve(dependencies []string) ([]Skill, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	visited := make(map[string]bool)
	inStack := make(map[string]bool)
	var order []Skill

	var visit func(name string) error
	visit = func(name string) error {
		if inStack[name] {
			return fmt.Errorf("registry: dependency cycle detected at %q", name)
		}
		if visited[name] {
			return nil
		}
		skill, ok := r.skills[name]
		if !ok {
			return fmt.Errorf("registry: dependency %q is not installed", name)
		}
		inStack[name] = true
		for _, dep := range skill.Dependencies {
			depName := depBaseName(dep)
			if err := visit(depName); err != nil {
				return err
			}
		}
		inStack[name] = false
		visited[name] = true
		order = append(order, skill)
		return nil
	}

	for _, dep := range dependencies {
		if err := visit(depBaseName(dep)); err != nil {
			return nil, err
		}
	}
	return order, nil
}

// depBaseName strips a version suffix ("name@1.2.3" → "name").
func depBaseName(dep string) string {
	for i, c := range dep {
		if c == '@' {
			return dep[:i]
		}
	}
	return dep
}
