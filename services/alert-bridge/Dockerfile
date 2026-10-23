# alert-bridge image (owner: M7). Build from the repo root:
#   docker build -f services/alert-bridge/Dockerfile -t moderaguard/alert-bridge .
FROM python:3.12-slim AS builder
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements/ requirements/
COPY services/alert-bridge/requirements.txt services/alert-bridge/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip pip install --prefix=/install -r services/alert-bridge/requirements.txt

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MODERAGUARD_ROOT=/app
RUN useradd --create-home --uid 10001 app
COPY --from=builder /install /usr/local
WORKDIR /app
COPY services/alert-bridge/ ./
RUN mkdir -p /app/reports /app/models && chown -R app /app
USER app
EXPOSE 8090
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8090/health')"
CMD ["uvicorn", "bridge:app", "--host", "0.0.0.0", "--port", "8090"]
