.PHONY: build test lint typecheck format coverage quality clean proto proto-python \
        up down logs run api dashboard \
        fe-install fe-build fe-lint fe-typecheck fe-format \
        foreman-plugins-install foreman-plugins-check \
        py-test py-lint \
        test-db test-handler test-integration all \
        db-up db-down \
        dev dev-down \
        otel-up otel-down otel-logs

GO_PACKAGES := $(shell go list ./... | rg -v '^github.com/benebsworth/omega/(web/)?dashboard/node_modules/' | sed 's|^github.com/benebsworth/omega|.|')

# ---------------------------------------------------------------------------
# Go build / test
# ---------------------------------------------------------------------------

build:
	go build ./...

test:
	go test $(GO_PACKAGES) -v -timeout 30s

test-db:
	go test ./internal/db/... -v -timeout 30s

test-handler:
	go test ./internal/handler/... -v -timeout 30s

## test-integration: run all Postgres integration tests (requires TEST_DATABASE_URL)
test-integration:
	TEST_DATABASE_URL=$(TEST_DATABASE_URL) go test $(GO_PACKAGES) -v -timeout 120s

## db-up: start Postgres via docker-compose (for local development)
db-up:
	docker compose up -d postgres
	@echo "Postgres available at postgres://omega:omega@localhost:5432/omega"
	@echo "Export: export DATABASE_URL=postgres://omega:omega@localhost:5432/omega?sslmode=disable"
	@echo "Export: export TEST_DATABASE_URL=postgres://omega:omega@localhost:5432/omega?sslmode=disable"

## db-down: stop Postgres container
db-down:
	docker compose stop postgres

# ---------------------------------------------------------------------------
# Full dev stack — single command to bring up the entire local environment
# ---------------------------------------------------------------------------

## dev: start Postgres + Python pipeline server (background) + Go API (foreground)
##      Requires: docker, python3, go
##      Set DATABASE_URL before running if Postgres is external:
##        export DATABASE_URL=postgres://omega:omega@localhost:5432/omega?sslmode=disable
dev:
	@echo "── Starting Postgres ──────────────────────────────────────────────────"
	docker compose up -d postgres
	@echo "── Starting Python pipeline server (background, port 9090) ────────────"
	DATABASE_URL=postgres://omega:omega@localhost:5432/omega?sslmode=disable \
	  OMEGA_PYTHON_PIPELINE_ADDR=http://localhost:9090 \
	  python3 -m omega.bridge.pipeline_server &
	@echo "Pipeline server PID: $$!"
	@echo "── Waiting 2s for pipeline server to boot ──────────────────────────────"
	sleep 2
	@echo "── Starting Go API (foreground) ────────────────────────────────────────"
	@echo "  Press Ctrl+C to stop.  Run 'make dev-down' to clean up background processes."
	DATABASE_URL=postgres://omega:omega@localhost:5432/omega?sslmode=disable \
	  OMEGA_PYTHON_PIPELINE_ADDR=http://localhost:9090 \
	  OTLP_ENDPOINT=http://localhost:4318 \
	  go run ./cmd/omega-api

## dev-down: stop Postgres and any background pipeline server processes
dev-down:
	@echo "── Stopping Postgres ───────────────────────────────────────────────────"
	docker compose stop postgres
	@echo "── Killing pipeline server (port 9090) ─────────────────────────────────"
	-lsof -ti:9090 | xargs kill -9 2>/dev/null || true
	@echo "Dev stack stopped."

# ---------------------------------------------------------------------------
# Proto generation
# ---------------------------------------------------------------------------

proto:
	buf generate

## proto-python: generate Python protobuf bindings from proto/omega/v1/ into gen/python/
##   Requires betterproto[compiler] in the active venv:  uv pip install "betterproto[compiler]"
proto-python:
	mkdir -p gen/python
	PATH="$$(pwd)/.venv/bin:$$PATH" protoc \
	  --plugin=protoc-gen-python_betterproto=.venv/bin/protoc-gen-python_betterproto \
	  --python_betterproto_out=gen/python \
	  -I proto \
	  $$(find proto/omega/v1 -name "*.proto" | sort)
	touch gen/python/__init__.py gen/python/omega/__init__.py
	@# Suppress ruff + mypy on generated file (explicit file paths bypass pyproject.toml exclude)
	sed -i '' '1s/^/# mypy: ignore-errors\n# ruff: noqa\n/' gen/python/omega/v1.py

# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

fe-install:
	cd dashboard && npm install

fe-build:
	cd dashboard && npm run build

fe-lint:
	cd dashboard && npm run lint
	cd web/dashboard && npm run lint

fe-typecheck:
	cd dashboard && npm run typecheck
	cd web/dashboard && npm run typecheck

fe-format:
	cd dashboard && npx prettier --write 'src/**/*.{ts,tsx,css}'

# ---------------------------------------------------------------------------
# Foreman use-case shells (foreman-plugins/)
#
# Deliberately NOT part of `make quality` or `make build`. These are built and
# shipped by the harness repo (~/projects/omega/harness reads
# foreman-plugins.json and compiles them into its bundle); what runs here is the
# check that they still typecheck against the plugin contract and that their own
# tests pass. Both need the harness checked out beside this repo, because the
# kit arrives as a `file:` dependency pointing into it — so this stays opt-in
# rather than breaking the main pipeline for anyone without it.
# ---------------------------------------------------------------------------

## foreman-plugins-install: install the shells' dev deps and link the kit (needs ../harness)
foreman-plugins-install:
	cd harness && pnpm --filter @omega-harness/usecase-kit build
	cd foreman-plugins && npm install

## foreman-plugins-check: typecheck + test the Victoria and Polymarket Foreman shells
foreman-plugins-check:
	cd foreman-plugins && npm run check

# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------

py-test:
	python -m pytest tests/ -v

py-lint:
	@which ruff > /dev/null 2>&1 && ruff check omega/ || echo "ruff not installed, skipping"

# ---------------------------------------------------------------------------
# Quality targets (all three layers)
# ---------------------------------------------------------------------------

## lint: run all linters (Python + Go + React)
lint:
	@echo "── Python: ruff ──────────────────────────────"
	python3 -m ruff check omega/ tests/
	@echo "── Go: vet + golangci-lint ───────────────────"
	go vet $(GO_PACKAGES)
	@which golangci-lint > /dev/null 2>&1 && golangci-lint run $(GO_PACKAGES) || echo "golangci-lint not installed, skipping"
	@echo "── React: eslint ─────────────────────────────"
	cd dashboard && npm run lint
	@echo "── React (web/dashboard): eslint ─────────────"
	cd web/dashboard && npm run lint

## format: auto-format all code (Python + Go + React)
format:
	@echo "── Python: ruff format ───────────────────────"
	python3 -m ruff format omega/ tests/
	python3 -m ruff check --fix omega/ tests/
	@echo "── Go: gofumpt ───────────────────────────────"
	@which gofumpt > /dev/null 2>&1 && gofumpt -l -w . || go fmt ./...
	@echo "── React: prettier ───────────────────────────"
	cd dashboard && npx prettier --write 'src/**/*.{ts,tsx,css}'

## typecheck: mypy (Python) + tsc (React)
typecheck:
	@echo "── Python: mypy ──────────────────────────────"
	python3 -m mypy omega/ tests/
	@echo "── React: tsc ────────────────────────────────"
	cd dashboard && npm run typecheck
	@echo "── React (web/dashboard): tsc ────────────────"
	cd web/dashboard && npm run typecheck

## coverage: run tests with coverage reports
coverage:
	@echo "── Python coverage ───────────────────────────"
	python3 -m pytest \
		--cov=omega \
		--cov-report=xml:coverage-python.xml \
		--cov-report=term-missing \
		tests/
	@echo "── Go coverage ───────────────────────────────"
	go test -coverprofile=coverage-go.out -covermode=atomic $(GO_PACKAGES)
	go tool cover -func=coverage-go.out | tail -1

## train-router: offline train AttentionRouter from coordination_outcomes DB
train-router:
	DATABASE_URL=$${DATABASE_URL:-postgresql://omega:omega@localhost:5432/omega} \
		python3 scripts/train_router.py

## quality: full CI pipeline (lint + typecheck + test)
quality:
	@echo "Running full quality pipeline..."
	bash scripts/ci.sh

# ---------------------------------------------------------------------------
# Local dev
# ---------------------------------------------------------------------------

run:
	python -m omega.examples.vectora_main

api:
	go run ./cmd/omega-api

dashboard:
	cd dashboard && npm run dev

# ---------------------------------------------------------------------------
# Docker Compose
# ---------------------------------------------------------------------------

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

monitoring-up:
	docker compose -f monitoring/docker-compose.yml up -d
	@echo "Prometheus : http://localhost:9091"
	@echo "Grafana    : http://localhost:3000  (admin / omega)"

monitoring-down:
	docker compose -f monitoring/docker-compose.yml down

monitoring-status:
	docker compose -f monitoring/docker-compose.yml ps

otel-up:
	cd deploy && docker compose -f docker-compose.otel.yaml up -d
	@echo "OTel Collector gRPC : localhost:4317"
	@echo "OTel Collector HTTP : localhost:4318"
	@echo "OTel Metrics        : http://localhost:8889/metrics"
	@echo "Tempo HTTP API      : http://localhost:3200"
	@echo "Grafana             : http://localhost:3001  (admin / omega)"

otel-down:
	cd deploy && docker compose -f docker-compose.otel.yaml down

otel-logs:
	cd deploy && docker compose -f docker-compose.otel.yaml logs -f

# ---------------------------------------------------------------------------
# Build all
# ---------------------------------------------------------------------------

all: build fe-build py-test

clean:
	rm -f omega-api
	rm -f coverage-go.out coverage-python.xml junit-python.xml
	rm -rf dashboard/dist
