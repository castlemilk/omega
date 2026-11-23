#!/bin/sh
# Build the exact server-side module embedded by Studio. The Go toolchain,
# linker flags and protobuf dependency lock are part of its identity.
set -eu
if [ "$#" -ne 1 ]; then
  echo "Usage: scripts/build-venture-delivery-inspector.sh /absolute/path/delivery-check.wasm" >&2
  exit 2
fi
case "$1" in /*) ;; *) echo "Specify an absolute output path." >&2; exit 2 ;; esac
cd "$(dirname "$0")/.."
export GOTOOLCHAIN=go1.27.4 CGO_ENABLED=0 GOOS=wasip1 GOARCH=wasm
go build -trimpath -buildvcs=false -buildmode=c-shared -ldflags='-s -w -buildid=' -o "$1" ./cmd/omega-delivery-check
