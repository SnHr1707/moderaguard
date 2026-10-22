# Trainer image (owner: M3): runs the DVC pipeline and registers models in MLflow.
# Used once to bootstrap a fresh stack (`make bootstrap`) and by Jenkins.
#   docker build -f infra/trainer/Dockerfile -t moderaguard/trainer .
FROM python:3.12-slim
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10 PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MODERAGUARD_ROOT=/workspace
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
COPY requirements/ requirements/
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements/train.txt
COPY pyproject.toml README.md ./
COPY src/ src/
RUN --mount=type=cache,target=/root/.cache/pip pip install --no-deps -e .
COPY infra/trainer/bootstrap.sh /usr/local/bin/bootstrap
CMD ["bootstrap"]
