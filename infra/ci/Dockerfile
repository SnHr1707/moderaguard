# CI image (owner: M6): everything the Jenkins stages need, on Python 3.12.
# Jenkins runs lint, tests, the DVC pipeline and kubectl inside this image, so
# CI uses exactly the pinned versions the services use.
FROM python:3.12-slim
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10 PIP_DISABLE_PIP_VERSION_CHECK=1
ARG KUBECTL_VERSION=v1.33.4
ARG KUSTOMIZE_VERSION=v5.7.1
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates && rm -rf /var/lib/apt/lists/* \
 && curl -fsSL -o /usr/local/bin/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
 && chmod +x /usr/local/bin/kubectl \
 && curl -fsSL "https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2F${KUSTOMIZE_VERSION}/kustomize_${KUSTOMIZE_VERSION}_linux_amd64.tar.gz" \
    | tar xz -C /usr/local/bin kustomize
WORKDIR /workspace
COPY requirements/ /tmp/requirements/
RUN --mount=type=cache,target=/root/.cache/pip pip install -r /tmp/requirements/dev.txt
ENV PYTHONPATH=/workspace/src MODERAGUARD_ROOT=/workspace MLFLOW_DISABLE_AGENT_HINT=1
