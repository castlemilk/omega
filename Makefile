.PHONY: build test lint typecheck proto all clean

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

fe-install:
	cd dashboard && npm install

fe-build:
	cd dashboard && npm run build

fe-lint:
	cd dashboard && npm run lint

fe-typecheck:
	cd dashboard && npm run typecheck

all: build fe-build

clean:
	rm -f omega-api
	rm -rf dashboard/dist
