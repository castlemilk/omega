package conformance

import (
	"fmt"
	"strings"
)

// GenerateReport produces a Markdown-formatted conformance report from results.
func GenerateReport(results []ConformanceResult) string {
	if len(results) == 0 {
		return "# Conformance Report\n\n_No tests were run._\n"
	}

	passed, failed := 0, 0
	for _, r := range results {
		if r.Passed {
			passed++
		} else {
			failed++
		}
	}

	var sb strings.Builder
	sb.WriteString("# Conformance Report\n\n")
	sb.WriteString(fmt.Sprintf("**Total**: %d | **Passed**: %d | **Failed**: %d\n\n", len(results), passed, failed))
	sb.WriteString("| Test | Result | Duration | Details |\n")
	sb.WriteString("|------|--------|----------|---------|\n")

	for _, r := range results {
		status := "✅ PASS"
		if !r.Passed {
			status = "❌ FAIL"
		}
		details := strings.ReplaceAll(r.Details, "|", "\\|")
		sb.WriteString(fmt.Sprintf("| `%s` | %s | %s | %s |\n",
			r.TestName, status, r.Duration.Round(1000).String(), details))
	}

	if failed > 0 {
		sb.WriteString("\n## Failures\n\n")
		for _, r := range results {
			if !r.Passed {
				sb.WriteString(fmt.Sprintf("### `%s`\n\n%s\n\n", r.TestName, r.Details))
			}
		}
	}

	return sb.String()
}

// CompareReports returns a Markdown diff between two sets of conformance results,
// highlighting regressions (previously passing, now failing) and improvements
// (previously failing, now passing).
func CompareReports(old, new []ConformanceResult) string {
	oldMap := make(map[string]bool, len(old))
	for _, r := range old {
		oldMap[r.TestName] = r.Passed
	}
	newMap := make(map[string]bool, len(new))
	for _, r := range new {
		newMap[r.TestName] = r.Passed
	}

	var regressions, improvements, unchanged []string

	for _, r := range new {
		oldPassed, existed := oldMap[r.TestName]
		if !existed {
			continue
		}
		switch {
		case oldPassed && !r.Passed:
			regressions = append(regressions, r.TestName)
		case !oldPassed && r.Passed:
			improvements = append(improvements, r.TestName)
		default:
			unchanged = append(unchanged, r.TestName)
		}
	}

	var sb strings.Builder
	sb.WriteString("# Conformance Comparison\n\n")

	if len(regressions) == 0 && len(improvements) == 0 {
		sb.WriteString("No changes detected.\n")
		return sb.String()
	}

	if len(regressions) > 0 {
		sb.WriteString(fmt.Sprintf("## ⚠️ Regressions (%d)\n\n", len(regressions)))
		for _, name := range regressions {
			sb.WriteString(fmt.Sprintf("- `%s` — was PASS, now FAIL\n", name))
		}
		sb.WriteString("\n")
	}

	if len(improvements) > 0 {
		sb.WriteString(fmt.Sprintf("## ✅ Improvements (%d)\n\n", len(improvements)))
		for _, name := range improvements {
			sb.WriteString(fmt.Sprintf("- `%s` — was FAIL, now PASS\n", name))
		}
		sb.WriteString("\n")
	}

	_ = unchanged
	return sb.String()
}
