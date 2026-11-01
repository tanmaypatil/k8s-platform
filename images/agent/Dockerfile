# Agent image: orchestrator, build agent and dashboard (Python stdlib + kubectl).
# Build from the repo root:
#   docker build -t k8s-platform/agent:dev -f images/agent/Dockerfile .
FROM python:3.12-slim

ARG TARGETARCH=amd64
ARG KUBECTL_VERSION=v1.33.5
ADD https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${TARGETARCH}/kubectl /usr/local/bin/kubectl
RUN chmod +x /usr/local/bin/kubectl

WORKDIR /app
COPY agent/ /app/agent/
COPY dashboard/ /app/dashboard/
COPY manifests/templates/ /app/templates/

ENV PYTHONUNBUFFERED=1 \
    TEMPLATE_DIR=/app/templates
CMD ["python", "/app/agent/orchestrator.py"]
