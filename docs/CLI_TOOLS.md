# CLI Tools Inventory

Audited 2026-03-24. All tools confirmed available on dev machine (macOS, darwin/arm64).

## Go

| Tool | Version | Command |
|------|---------|---------|
| `go` | go1.26.0 darwin/arm64 | `/opt/homebrew/bin/go` |
| `golangci-lint` | 2.10.1 | `/opt/homebrew/bin/golangci-lint` |
| `buf` | 1.47.2 | `/opt/homebrew/bin/buf` |

### Usage
```bash
# Build all packages
go build ./...

# Run all tests
go test ./...

# Lint
golangci-lint run ./...

# Generate protobuf
cd proto && buf generate
buf lint
```

## Python

| Tool | Version | Command |
|------|---------|---------|
| `python3` | 3.14.3 | `/opt/homebrew/bin/python3` |
| `pip3` | 26.0 | `/opt/homebrew/bin/pip3` |
| `pytest` | 9.0.2 | `/opt/homebrew/bin/pytest` |
| `ruff` | 0.15.7 | `/opt/homebrew/bin/ruff` |
| `mypy` | 1.19.1 | `/opt/homebrew/bin/mypy` |

### Usage
```bash
# Run tests
pytest tests/ -v

# Lint + format
ruff check omega/
ruff format omega/

# Type check
mypy omega/

# Run specific test
pytest tests/test_conviction.py -v
```

## Node / Frontend

| Tool | Version | Command |
|------|---------|---------|
| `node` | v22.9.0 | nvm-managed |
| `npm` | 10.8.3 | nvm-managed |

### Usage
```bash
npm install
npm run build
npm run dev
```

## Docker

| Tool | Version | Command |
|------|---------|---------|
| `docker` | 29.2.1 | `/opt/homebrew/bin/docker` |

Note: `docker-compose` is not installed as a standalone binary — use `docker compose` (plugin).

```bash
# Start services
docker compose up -d

# Stop
docker compose down

# View logs
docker compose logs -f
```

## Database

| Tool | Version | Command |
|------|---------|---------|
| `psql` | PostgreSQL 17.6 | `/opt/homebrew/opt/postgresql@17/bin/psql` |

### Usage
```bash
# Connect to local DB
psql -U postgres -d omega

# Run a query file
psql -U postgres -d omega -f schema.sql

# Quick query
psql -U postgres -d omega -c "SELECT * FROM cycle_results LIMIT 5;"
```

## GitHub

| Tool | Version | Command |
|------|---------|---------|
| `gh` | 2.88.1 | `/opt/homebrew/bin/gh` |

### Usage
```bash
# Create PR
gh pr create --title "..." --body "..."

# List open PRs
gh pr list

# View issue
gh issue view 42

# Check CI status
gh run list --branch main
```

## AI CLIs

| Tool | Version | Command | Notes |
|------|---------|---------|-------|
| `claude` | 2.1.81 (Claude Code) | `~/.local/bin/claude` | Anthropic Claude Code CLI |
| `codex` | 0.116.0 | `~/.nvm/.../bin/codex` | OpenAI Codex CLI (`@openai/codex`) |
| `openai` | 2.9.0 | `/opt/homebrew/bin/openai` | OpenAI Python SDK CLI |

### Usage
```bash
# Run Claude Code interactively
claude

# Run Codex
codex "explain this function"

# OpenAI CLI (models, completions)
openai api models.list
```

## Utilities

| Tool | Version | Command |
|------|---------|---------|
| `curl` | 8.7.1 | `/usr/bin/curl` |
| `jq` | 1.7.1 | `/opt/homebrew/bin/jq` |

### Usage
```bash
# Test an API endpoint
curl -s http://localhost:8080/healthz | jq .

# Parse JSON output
some-command | jq '.items[].name'
```

## Local Assessment Workflow

For a full local quality check before pushing:

```bash
# 1. Go: build, vet, lint, test
go build ./...
go vet ./...
golangci-lint run ./...
go test ./... -race

# 2. Python: lint, types, tests
ruff check omega/
mypy omega/
pytest tests/ -v

# 3. Proto: lint + generate
cd proto && buf lint && buf generate

# 4. Infra: start local stack
docker compose up -d

# 5. GitHub: open PR after all pass
gh pr create --title "feat: ..." --body "..."
```
