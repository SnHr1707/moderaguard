"""Model service: serves ONE task model over HTTP (owner: M5).

The same code runs three times with different settings:
  TASK=toxicity -> toxicity-svc     TASK=spam -> spam-svc     TASK=langid -> langid-svc

Settings (environment variables):
  TASK          toxicity | spam | langid
  MODEL_SOURCE  mlflow | local
  MODEL_ALIAS   champion | challenger   (canary pods use challenger)
  VARIANT       stable | canary         (label on every metric)
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from moderaguard.responsible.explain import explain
from moderaguard.serving.loader import load_model
from moderaguard.serving.metrics import LANGUAGES, MODEL_INFO, SCORES, instrument

TASK = os.environ.get("TASK", "toxicity")
VARIANT = os.environ.get("VARIANT", "stable")
SERVICE = f"{TASK}-svc"
RETRY_SECONDS = int(os.environ.get("MODEL_LOAD_RETRY_SECONDS", 15))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger(SERVICE)

state: dict = {"model": None}


def _load() -> None:
    model = load_model(TASK)
    state["model"] = model
    MODEL_INFO.labels(SERVICE, VARIANT, str(getattr(model, "version", "unknown"))).set(1)
    log.info("loaded %s model version %s", TASK, getattr(model, "version", "unknown"))


async def _load_until_ready() -> None:
    """Keep trying to load the model. On a fresh stack the registry may still be
    empty when this service starts; /ready returns 503 until a model is loaded."""
    while state["model"] is None:
        try:
            await asyncio.to_thread(_load)
        except Exception as e:  # noqa: BLE001
            log.warning("model not available yet (%s); retrying in %ss", e, RETRY_SECONDS)
            await asyncio.sleep(RETRY_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        _load()
        loader = None
    except Exception as e:  # noqa: BLE001
        log.warning("model failed to load at startup (%s); retrying in the background", e)
        loader = asyncio.create_task(_load_until_ready())
    yield
    if loader is not None:
        loader.cancel()


app = FastAPI(title=f"ModeraGuard {TASK} service", version="0.1.0", lifespan=lifespan)
instrument(app, SERVICE, VARIANT)


class PredictRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, max_length=256)


class ExplainRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    top_k: int = 5


def _model():
    if state["model"] is None:
        raise HTTPException(status_code=503, detail="model not loaded")
    return state["model"]


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": SERVICE, "variant": VARIANT}


@app.get("/ready")
def ready() -> dict:
    model = _model()
    return {"status": "ready", "task": TASK, "model_version": str(getattr(model, "version", "unknown"))}


@app.post("/predict")
def predict(req: PredictRequest) -> dict:
    model = _model()
    version = str(getattr(model, "version", "unknown"))
    if TASK == "langid":
        detected = model.detect(req.texts)
        for lang, _ in detected:
            LANGUAGES.labels(lang).inc()
        return {"languages": [d[0] for d in detected], "confidences": [d[1] for d in detected],
                "model_version": version}
    scores = model.score(req.texts)
    for s in scores:
        SCORES.labels(TASK, VARIANT).observe(s)
    return {"scores": scores, "model_version": version}


@app.post("/explain")
def explain_endpoint(req: ExplainRequest) -> dict:
    if TASK == "langid":
        raise HTTPException(status_code=400, detail="explanations are only available for scoring models")
    return {**explain(_model(), req.text, req.top_k), "model_version": str(getattr(_model(), "version", ""))}


@app.post("/reload")
def reload() -> dict:
    """Reload the model after an alias change in MLflow (promotion or rollback) without restarting."""
    _load()
    return ready()
