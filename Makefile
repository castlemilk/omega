.PHONY: build test lint typecheck format coverage quality clean proto \
        up down logs run api dashboard \
        fe-install fe-build fe-lint fe-typecheck fe-format \
        py-test py-lint \
        test-db test-handler all

# ---------------------------------------------------------------------------
# Go build / test
# ---------------------------------------------------------------------------

build:
	go build ./...

test:
	go test ./... -v -timeout 30s

test-db:
	go test ./internal/db/... -v -timeout 30s

test-handler:
	go test ./internal/handler/... -v -timeout 30s

# ---------------------------------------------------------------------------
# Proto generation
# ---------------------------------------------------------------------------

proto:
	buf generate

# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

fe-install:
	cd dashboard && npm install

fe-build:
	cd dashboard && npm run build

fe-lint:
	cd dashboard && npm run lint

fe-typecheck:
	cd dashboard && npm run typecheck

fe-format:
	cd dashboard && npx prettier --write 'src/**/*.{ts,tsx,css}'

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
	go vet ./...
	@which golangci-lint > /dev/null 2>&1 && golangci-lint run ./... || echo "golangci-lint not installed, skipping"
	@echo "── React: eslint ─────────────────────────────"
	cd dashboard && npm run lint

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

## coverage: run tests with coverage reports
coverage:
	@echo "── Python coverage ───────────────────────────"
	python3 -m pytest \
		--cov=omega \
		--cov-report=xml:coverage-python.xml \
		--cov-report=term-missing \
		tests/
	@echo "── Go coverage ───────────────────────────────"
	go test -coverprofile=coverage-go.out -covermode=atomic ./...
	go tool cover -func=coverage-go.out | tail -1

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

# ---------------------------------------------------------------------------
# Build all
# ---------------------------------------------------------------------------

all: build fe-build py-test

clean:
	rm -f omega-api
	rm -f coverage-go.out coverage-python.xml junit-python.xml
	rm -rf dashboard/dist
