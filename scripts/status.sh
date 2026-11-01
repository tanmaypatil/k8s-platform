#!/usr/bin/env bash
# Show build status from the build-status ConfigMap, and the Jobs behind it.
set -euo pipefail
kubectl -n builds exec deploy/dashboard -- python /app/agent/status_store.py
echo
kubectl -n builds get jobs -l app.kubernetes.io/part-of=k8s-platform \
  -L k8s-platform/stage,k8s-platform/repo,k8s-platform/java --sort-by=.status.startTime
