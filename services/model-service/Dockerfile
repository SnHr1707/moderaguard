# model-service image (owner: M5). Build from the repo root:
#   docker build -f services/model-service/Dockerfile -t moderaguard/model-service .
FROM python:3.12-slim AS builder
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements/ requirements/
COPY services/model-service/requirements.txt services/model-service/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip pip install --prefix=/install -r services/model-service/requirements.txt
COPY pyproject.toml README.md ./
COPY src/ src/
RUN --mount=type=cache,target=/root/.cache/pip pip install --prefix=/install --no-deps .

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MODERAGUARD_ROOT=/app
RUN useradd --create-home --uid 10001 app
COPY --from=builder /install /usr/local
WORKDIR /app
COPY services/model-service/ ./
RUN mkdir -p /app/reports /app/models && chown -R app /app
USER app
EXPOSE 8001
CMD ["sh", "-c", "uvicorn model_service:app --host 0.0.0.0 --port ${PORT:-8001}"]
