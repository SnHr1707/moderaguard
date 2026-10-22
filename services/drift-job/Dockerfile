# drift-job image (owner: M7). Build from the repo root:
#   docker build -f services/drift-job/Dockerfile -t moderaguard/drift-job .
FROM python:3.12-slim AS builder
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements/ requirements/
COPY services/drift-job/requirements.txt services/drift-job/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip pip install --prefix=/install -r services/drift-job/requirements.txt

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MODERAGUARD_ROOT=/app
RUN useradd --create-home --uid 10001 app
COPY --from=builder /install /usr/local
WORKDIR /app
COPY services/drift-job/ ./
RUN mkdir -p /app/reports /app/models && chown -R app /app
USER app
CMD ["python", "drift.py", "run"]
