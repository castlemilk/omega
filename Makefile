.PHONY: build test lint typecheck proto all clean \
        up down logs run api dashboard \
        fe-install fe-build fe-lint fe-typecheck \
        py-test py-lint

# ── Go ────────────────────────────────────────────────────────────────────────

build:
	go build ./...

test:
	go test ./... -v -timeout 30s

lint:
	go vet ./...
	@which golangci-lint > /dev/null 2>&1 && golangci-lint run ./... || echo "golangci-lint not installed, skipping"

test-db:
	go test ./internal/db/... -v -timeout 30s

test-handler:
	go test ./internal/handler/... -v -timeout 30s

proto:
	buf generate

# ── React dashboard ────────────────────────────────────────────────────────────

fe-install:
	cd dashboard && npm install

fe-build:
	cd dashboard && npm run build

fe-lint:
	cd dashboard && npm run lint

fe-typecheck:
	cd dashboard && npm run typecheck

# ── Python ────────────────────────────────────────────────────────────────────

py-test:
	python -m pytest tests/ -v

py-lint:
	@which ruff > /dev/null 2>&1 && ruff check omega/ || echo "ruff not installed, skipping"

# ── Local dev (no Docker) ──────────────────────────────────────────────────────

run:
	python -m omega.examples.vectora_main

api:
	go run ./cmd/omega-api

dashboard:
	cd dashboard && npm run dev

# ── Docker Compose ────────────────────────────────────────────────────────────

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

# ── Aggregate targets ─────────────────────────────────────────────────────────

all: build fe-build py-test

clean:
	rm -f omega-api
	rm -rf dashboard/dist
