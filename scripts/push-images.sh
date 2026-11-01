#!/usr/bin/env bash
# Build the three platform images and push them to a registry (what a CI pipeline would do).
#   docker login ghcr.io
#   REGISTRY=ghcr.io/my-org TAG=1.0.0 ./scripts/push-images.sh
# Builds for Intel and Apple Silicon nodes by default; override with PLATFORMS=linux/amd64.
set -euo pipefail
cd "$(dirname "$0")/.."

: "${REGISTRY:?set REGISTRY, e.g. ghcr.io/my-org}"
TAG="${TAG:-latest}"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"

build() {  # name dockerfile context
  echo "==> $REGISTRY/$1:$TAG ($PLATFORMS)"
  docker buildx build --platform "$PLATFORMS" --push -t "$REGISTRY/$1:$TAG" -f "$2" "$3"
}
build java8-maven  images/java8-maven/Dockerfile  images
build java17-maven images/java17-maven/Dockerfile images
build agent        images/agent/Dockerfile        .

echo "Pushed. Deploy with: REGISTRY=$REGISTRY TAG=$TAG ./scripts/up.sh"
