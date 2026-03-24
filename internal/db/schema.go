package db

import (
	"context"
	"fmt"
	"strings"
	"unicode"
)

// EnsureProjectSchema creates the per-project Postgres schema if it does not
// already exist.  All project-specific tables should live under this schema.
//
// Schema name: project_<sanitized_id>
// Example: project_id "proj_victoria" → schema "project_proj_victoria"
func (d *DB) EnsureProjectSchema(ctx context.Context, projectID string) error {
	name := projectSchemaName(projectID)
	_, err := d.db.ExecContext(ctx, fmt.Sprintf(`CREATE SCHEMA IF NOT EXISTS %q`, name))
	if err != nil {
		return fmt.Errorf("ensure project schema %q: %w", name, err)
	}
	return nil
}

// ProjectSchemaName returns the Postgres schema name for the given project ID.
// Callers can use this to build schema-qualified table names:
//
//	tbl := db.ProjectSchemaName("proj_victoria") + ".goal_tracking"
func ProjectSchemaName(projectID string) string {
	return projectSchemaName(projectID)
}

func projectSchemaName(id string) string {
	return "project_" + sanitizeForSchema(id)
}

// sanitizeForSchema converts a project ID into a safe Postgres identifier
// component: lowercased, non-alphanumeric/underscore characters replaced by '_'.
func sanitizeForSchema(id string) string {
	var b strings.Builder
	for _, r := range strings.ToLower(id) {
		if unicode.IsLetter(r) || unicode.IsDigit(r) || r == '_' {
			b.WriteRune(r)
		} else {
			b.WriteRune('_')
		}
	}
	return b.String()
}
