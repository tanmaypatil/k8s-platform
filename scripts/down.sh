#!/usr/bin/env bash
# Delete the local cluster (and with it the PVC and all build data).
set -euo pipefail
CLUSTER_TOOL="${CLUSTER_TOOL:-kind}"
CLUSTER_NAME="${CLUSTER_NAME:-k8s-platform}"
if [[ "$CLUSTER_TOOL" == kind ]]; then kind delete cluster --name "$CLUSTER_NAME"
else minikube delete -p "$CLUSTER_NAME"; fi
