# consumer image (owner: M2). Build from the repo root:
#   docker build -f services/consumer/Dockerfile -t moderaguard/consumer .
FROM python:3.12-slim AS builder
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements/ requirements/
COPY services/consumer/requirements.txt services/consumer/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip pip install --prefix=/install -r services/consumer/requirements.txt
COPY pyproject.toml README.md ./
COPY src/ src/
RUN --mount=type=cache,target=/root/.cache/pip pip install --prefix=/install --no-deps .

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MODERAGUARD_ROOT=/app
RUN useradd --create-home --uid 10001 app
COPY --from=builder /install /usr/local
WORKDIR /app
COPY services/consumer/ ./
RUN mkdir -p /app/reports /app/models && chown -R app /app
USER app
CMD ["python", "consumer.py"]
