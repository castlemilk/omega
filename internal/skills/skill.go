// Package skills provides Skill packaging, distribution, and registry management
// for Omega agent capabilities.
package skills

import (
	"errors"
	"fmt"
	"regexp"
)

// depPattern validates a dependency reference: "name@version" or just "name".
var depPattern = regexp.MustCompile(`^[a-zA-Z0-9_-]+(@[0-9]+\.[0-9]+\.[0-9]+)?$`)

// Skill is the canonical representation of an Omega skill.
type Skill struct {
	Name         string         `json:"name"`
	Version      string         `json:"version"`
	Description  string         `json:"description"`
	Author       string         `json:"author"`
	Dependencies []string       `json:"dependencies"`
	EntryPoint   string         `json:"entry_point"`
	Config       map[string]any `json:"config"`
}

// SkillManifest is the metadata stored in the SKILL.md file inside a packaged
// skill archive. It intentionally omits Config to keep the manifest readable.
type SkillManifest struct {
	Name         string   `json:"name"`
	Version      string   `json:"version"`
	Description  string   `json:"description"`
	Author       string   `json:"author"`
	Dependencies []string `json:"dependencies"`
	EntryPoint   string   `json:"entry_point"`
}

// Validate checks that required fields are present and that dependency
// references conform to the expected format.
func Validate(skill Skill) error {
	var errs []error
	if skill.Name == "" {
		errs = append(errs, errors.New("name is required"))
	}
	if skill.Version == "" {
		errs = append(errs, errors.New("version is required"))
	}
	if skill.EntryPoint == "" {
		errs = append(errs, errors.New("entry_point is required"))
	}
	for _, dep := range skill.Dependencies {
		if !depPattern.MatchString(dep) {
			errs = append(errs, fmt.Errorf("invalid dependency format %q (expected name or name@x.y.z)", dep))
		}
	}
	return errors.Join(errs...)
}

// manifestFromSkill converts a Skill to its SkillManifest representation.
func manifestFromSkill(s Skill) SkillManifest {
	return SkillManifest{
		Name:         s.Name,
		Version:      s.Version,
		Description:  s.Description,
		Author:       s.Author,
		Dependencies: s.Dependencies,
		EntryPoint:   s.EntryPoint,
	}
}
