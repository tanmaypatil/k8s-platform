#!/usr/bin/env bash
# Create a local cluster, build the images, load them into the cluster and deploy.
#   ./scripts/up.sh                    # kind (default)
#   CLUSTER_TOOL=minikube ./scripts/up.sh
#   REGISTRY=ghcr.io/my-org TAG=1.0.0 ./scripts/up.sh   # use prebuilt images, skip build + load
set -euo pipefail
cd "$(dirname "$0")/.."

CLUSTER_TOOL="${CLUSTER_TOOL:-kind}"
CLUSTER_NAME="${CLUSTER_NAME:-k8s-platform}"
KIND_CONFIG="${KIND_CONFIG:-cluster/kind-config.yaml}"
REGISTRY="${REGISTRY:-}"
TAG="${TAG:-latest}"
IMAGES=(k8s-platform/java8-maven:dev k8s-platform/java17-maven:dev k8s-platform/agent:dev)

echo "==> Cluster ($CLUSTER_TOOL)"
if [[ "$CLUSTER_TOOL" == kind ]]; then
  kind get clusters | grep -qx "$CLUSTER_NAME" || kind create cluster --name "$CLUSTER_NAME" --config "$KIND_CONFIG"
  kubectl config use-context "kind-$CLUSTER_NAME" >/dev/null
else
  minikube status -p "$CLUSTER_NAME" >/dev/null 2>&1 || minikube start -p "$CLUSTER_NAME" --cpus 4 --memory 6g
  kubectl config use-context "$CLUSTER_NAME" >/dev/null
fi

if [[ -n "$REGISTRY" ]]; then
  echo "==> Using prebuilt images from $REGISTRY (tag $TAG)"
  kubectl kustomize manifests/overlays/registry \
    | sed -e "s#REGISTRY_PLACEHOLDER#${REGISTRY}#g" -e "s#TAG_PLACEHOLDER#${TAG}#g" \
    | kubectl apply -f -
  kubectl -n builds get secret registry-creds >/dev/null 2>&1 || cat <<MSG
    Note: no registry-creds secret in namespace builds. That is fine for a public registry.
    For a private one, create it and re-run:
      kubectl -n builds create secret docker-registry registry-creds \\
        --docker-server=<registry host> --docker-username=<user> --docker-password=<token>
MSG
else
  echo "==> Building images"
  docker build -t k8s-platform/java8-maven:dev  -f images/java8-maven/Dockerfile  images
  docker build -t k8s-platform/java17-maven:dev -f images/java17-maven/Dockerfile images
  docker build -t k8s-platform/agent:dev        -f images/agent/Dockerfile        .

  echo "==> Loading images into the cluster"
  for img in "${IMAGES[@]}"; do
    if [[ "$CLUSTER_TOOL" == kind ]]; then kind load docker-image "$img" --name "$CLUSTER_NAME"
    else minikube -p "$CLUSTER_NAME" image load "$img"; fi
  done

  echo "==> Applying manifests"
  kubectl apply -k manifests/base
fi
kubectl -n builds rollout restart deploy/dashboard >/dev/null   # pick up a rebuilt agent image
kubectl -n builds rollout status deploy/dashboard --timeout=180s

echo
if [[ "$CLUSTER_TOOL" == kind ]]; then
  echo "Dashboard: http://localhost:8080"
else
  echo "Dashboard: run  minikube -p $CLUSTER_NAME service dashboard -n builds"
fi
echo "Trigger a build: ./scripts/trigger.sh"
