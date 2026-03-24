#!/usr/bin/env bash
# scripts/ci.sh — Full CI quality pipeline
# Usage: bash scripts/ci.sh
# Exit codes: 0 = all passed, non-zero = first failure
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

GO_PACKAGES=($(go list ./... | rg -v '^github.com/benebsworth/omega/(web/)?dashboard/node_modules/' | sed 's#^github.com/benebsworth/omega#.#'))

FAILED=0
STEP=0

run_step() {
    local name="$1"
    shift
    STEP=$((STEP + 1))
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Step $STEP: $name"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    if "$@"; then
        echo "  ✓ $name passed"
    else
        echo "  ✗ $name FAILED"
        FAILED=$((FAILED + 1))
    fi
}

# ---------------------------------------------------------------------------
# Python quality
# ---------------------------------------------------------------------------

run_step "Python: ruff lint" \
    python3 -m ruff check omega/ tests/

run_step "Python: ruff format check" \
    python3 -m ruff format --check omega/ tests/

run_step "Python: mypy type check" \
    python3 -m mypy omega/ tests/

run_step "Python: pytest + coverage" \
    python3 -m pytest \
        --cov=omega \
        --cov-report=xml:coverage-python.xml \
        --cov-report=term-missing \
        --junitxml=junit-python.xml \
        -n auto \
        tests/

# ---------------------------------------------------------------------------
# Go quality
# ---------------------------------------------------------------------------

run_step "Go: vet" \
    go vet "${GO_PACKAGES[@]}"

run_step "Go: golangci-lint" \
    golangci-lint run "${GO_PACKAGES[@]}"

run_step "Go: test + coverage" \
    go test \
        -coverprofile=coverage-go.out \
        -covermode=atomic \
        "${GO_PACKAGES[@]}" \
        -timeout 60s

# Generate Go coverage report
if [ -f coverage-go.out ]; then
    go tool cover -func=coverage-go.out | tail -1
fi

# ---------------------------------------------------------------------------
# React / TypeScript quality
# ---------------------------------------------------------------------------

run_step "React: tsc type check" \
    bash -c "cd dashboard && npm run typecheck"

run_step "React (web/dashboard): tsc type check" \
    bash -c "cd web/dashboard && npm run typecheck"

run_step "React: ESLint" \
    bash -c "cd dashboard && npm run lint"

run_step "React (web/dashboard): ESLint" \
    bash -c "cd web/dashboard && npm run lint"

run_step "React: Prettier check" \
    bash -c "cd dashboard && npx prettier --check 'src/**/*.{ts,tsx,css}'"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ "$FAILED" -eq 0 ]; then
    echo "  ✓ All $STEP steps passed"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    exit 0
else
    echo "  ✗ $FAILED of $STEP steps FAILED"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    exit 1
fi
