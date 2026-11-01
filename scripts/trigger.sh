#!/usr/bin/env bash
# Start one orchestrator run (same thing the dashboard's "Run builds" button does).
#   ./scripts/trigger.sh          # start and follow the orchestrator logs
#   ./scripts/trigger.sh --no-follow
set -euo pipefail
BUILD_ID="run-$(date -u +%Y%m%d-%H%M%S)"

kubectl -n builds create job --from=cronjob/orchestrator "$BUILD_ID"
echo "Build id: $BUILD_ID"
[[ "${1:-}" == "--no-follow" ]] && exit 0

kubectl -n builds wait --for=condition=Ready pod -l "batch.kubernetes.io/job-name=$BUILD_ID" --timeout=120s >/dev/null
kubectl -n builds logs -f "job/$BUILD_ID"
