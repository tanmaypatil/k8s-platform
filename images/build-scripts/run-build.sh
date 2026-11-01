#!/usr/bin/env bash
# Entry point of the java8-maven / java17-maven build images.
# Runs inside a build Job pod, with the shared PVC mounted at /workspace.
set -euo pipefail

: "${SRC_DIR:?SRC_DIR is required}"
LOG_FILE="${LOG_FILE:-/workspace/logs/build.log}"
ARTIFACT_DIR="${ARTIFACT_DIR:-/workspace/artifacts}"
MAVEN_REPO="${MAVEN_REPO:-/workspace/m2}"     # shared Maven cache on the PVC
MAVEN_GOALS="${MAVEN_GOALS:-package}"

mkdir -p "$(dirname "$LOG_FILE")" "$ARTIFACT_DIR" "$MAVEN_REPO"

{
  echo "== Build started $(date -u +%Y-%m-%dT%H:%M:%SZ) on pod ${HOSTNAME}"
  echo "== Source: ${SRC_DIR}"
  java -version 2>&1
  mvn -v
  cd "$SRC_DIR"
  # shellcheck disable=SC2086
  mvn -B -ntp -Dmaven.repo.local="$MAVEN_REPO" $MAVEN_GOALS
  cp target/*.jar "$ARTIFACT_DIR"/ 2>/dev/null || true
  echo "== Artifacts in ${ARTIFACT_DIR}:"
  ls -l "$ARTIFACT_DIR"
  echo "== Build finished $(date -u +%Y-%m-%dT%H:%M:%SZ)"
} 2>&1 | tee "$LOG_FILE"
