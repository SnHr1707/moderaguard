"""Prometheus metrics shared by all ModeraGuard services (owners: M5 defines, M7 dashboards).

Metric names are part of the interface contract (docs/contracts.md): Grafana
dashboards and alert rules depend on them, so rename only together with M7.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from fastapi import FastAPI, Request, Response
from prometheus_client import Counter, Gauge, Histogram, make_asgi_app

REQUESTS = Counter(
    "moderaguard_requests_total", "HTTP requests handled", ["service", "variant", "endpoint", "status"]
)
LATENCY = Histogram(
    "moderaguard_latency_seconds", "Request latency", ["service", "variant", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
SCORES = Histogram(
    "moderaguard_score", "Model output scores", ["model", "variant"],
    buckets=tuple(i / 10 for i in range(1, 11)),
)
VERDICTS = Counter("moderaguard_verdicts_total", "Gateway verdicts", ["verdict", "variant", "reason"])
LANGUAGES = Counter("moderaguard_languages_total", "Detected languages", ["language"])
MODEL_INFO = Gauge("moderaguard_model_info", "Loaded model version (value is always 1)",
                   ["service", "variant", "version"])
FEEDBACK = Counter("moderaguard_feedback_total", "Moderator feedback", ["agreed"])


def instrument(app: FastAPI, service: str, variant: str) -> None:
    """Add a /metrics endpoint and per-request counters/latency to a FastAPI app."""
    app.mount("/metrics", make_asgi_app())

    @app.middleware("http")
    async def _measure(request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if path.startswith("/metrics"):
            return await call_next(request)
        start = time.perf_counter()
        status = "500"
        try:
            response = await call_next(request)
            status = str(response.status_code)
            return response
        finally:
            LATENCY.labels(service, variant, path).observe(time.perf_counter() - start)
            REQUESTS.labels(service, variant, path, status).inc()
