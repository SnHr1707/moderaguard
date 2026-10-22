"""Gateway: the public moderation API (owner: M5).

Flow for POST /moderate:
  1. langid-svc detects the language.
  2. Toxicity and spam models are English-only, so other languages go to
     human review instead of being scored with a model that never saw them.
  3. For English, toxicity-svc and spam-svc are called in parallel.
  4. Scores are combined into one verdict: allow / review / block.

Settings (environment variables, defaults in brackets):
  TOXICITY_URL [http://toxicity-svc:8001]  SPAM_URL [http://spam-svc:8002]  LANGID_URL [http://langid-svc:8003]
  TOXICITY_BLOCK [0.85]  TOXICITY_REVIEW [0.5]  SPAM_BLOCK [0.9]  SPAM_REVIEW [0.6]
  SUPPORTED_LANGUAGES [en]  VARIANT [stable]
  FEEDBACK_DSN  postgres DSN for moderator feedback; without it feedback goes to reports/feedback.jsonl
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from moderaguard.responsible.redact import redact
from moderaguard.serving.metrics import FEEDBACK, VERDICTS, instrument

VARIANT = os.environ.get("VARIANT", "stable")
URLS = {
    "toxicity": os.environ.get("TOXICITY_URL", "http://toxicity-svc:8001"),
    "spam": os.environ.get("SPAM_URL", "http://spam-svc:8002"),
    "langid": os.environ.get("LANGID_URL", "http://langid-svc:8003"),
}
THRESHOLDS = {
    "toxicity_block": float(os.environ.get("TOXICITY_BLOCK", 0.85)),
    "toxicity_review": float(os.environ.get("TOXICITY_REVIEW", 0.5)),
    "spam_block": float(os.environ.get("SPAM_BLOCK", 0.9)),
    "spam_review": float(os.environ.get("SPAM_REVIEW", 0.6)),
}
SUPPORTED_LANGUAGES = set(os.environ.get("SUPPORTED_LANGUAGES", "en").split(","))
FEEDBACK_DSN = os.environ.get("FEEDBACK_DSN")
FEEDBACK_FILE = Path(os.environ.get("FEEDBACK_FILE", "reports/feedback.jsonl"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("gateway")
state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # tests inject a client with a mock transport before startup
    state.setdefault("client", httpx.AsyncClient(timeout=httpx.Timeout(5.0)))
    yield
    await state["client"].aclose()
    state.clear()


app = FastAPI(title="ModeraGuard gateway", version="0.1.0", lifespan=lifespan)
instrument(app, "gateway", VARIANT)


class ModerateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    id: str | None = None


class ModerateResponse(BaseModel):
    id: str
    language: str
    language_confidence: float
    toxicity: float | None
    spam: float | None
    verdict: Literal["allow", "review", "block"]
    reasons: list[str]
    model_versions: dict[str, str]
    variant: str


class FeedbackRequest(BaseModel):
    id: str
    text: str
    predicted_verdict: Literal["allow", "review", "block"]
    correct_verdict: Literal["allow", "review", "block"]
    moderator: str = "anonymous"


async def _call(service: str, path: str, payload: dict) -> dict:
    try:
        r = await state["client"].post(f"{URLS[service]}{path}", json=payload)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        log.error("call to %s%s failed: %s", service, path, e)
        raise HTTPException(status_code=502, detail=f"{service} service unavailable") from e


def decide(toxicity: float | None, spam: float | None, language: str) -> tuple[str, list[str]]:
    """Turn scores into a verdict. Kept pure so it is easy to unit-test."""
    reasons: list[str] = []
    if language not in SUPPORTED_LANGUAGES:
        return "review", [f"unsupported_language:{language}"]
    verdict = "allow"
    if toxicity is not None and toxicity >= THRESHOLDS["toxicity_block"]:
        verdict, reasons = "block", reasons + ["toxic"]
    elif toxicity is not None and toxicity >= THRESHOLDS["toxicity_review"]:
        verdict, reasons = "review", reasons + ["possibly_toxic"]
    if spam is not None and spam >= THRESHOLDS["spam_block"]:
        verdict, reasons = "block", reasons + ["spam"]
    elif spam is not None and spam >= THRESHOLDS["spam_review"]:
        verdict = "review" if verdict == "allow" else verdict
        reasons.append("possibly_spam")
    return verdict, reasons


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "gateway", "variant": VARIANT}


@app.get("/ready")
async def ready() -> dict:
    results = await asyncio.gather(
        *(state["client"].get(f"{url}/ready") for url in URLS.values()), return_exceptions=True
    )
    status = {name: (not isinstance(r, Exception) and r.status_code == 200) for name, r in zip(URLS, results, strict=True)}
    if not all(status.values()):
        raise HTTPException(status_code=503, detail=status)
    return {"status": "ready", "dependencies": status}


@app.post("/moderate", response_model=ModerateResponse)
async def moderate(req: ModerateRequest) -> ModerateResponse:
    comment_id = req.id or uuid.uuid4().hex
    lang = await _call("langid", "/predict", {"texts": [req.text]})
    language, confidence = lang["languages"][0], lang["confidences"][0]
    versions = {"langid": lang["model_version"]}

    toxicity = spam = None
    if language in SUPPORTED_LANGUAGES:
        tox, spm = await asyncio.gather(
            _call("toxicity", "/predict", {"texts": [req.text]}),
            _call("spam", "/predict", {"texts": [req.text]}),
        )
        toxicity, spam = tox["scores"][0], spm["scores"][0]
        versions.update(toxicity=tox["model_version"], spam=spm["model_version"])

    verdict, reasons = decide(toxicity, spam, language)
    for reason in reasons or ["none"]:
        VERDICTS.labels(verdict, VARIANT, reason.split(":")[0]).inc()
    # Privacy: only the redacted text is ever logged
    log.info(json.dumps({"id": comment_id, "text": redact(req.text)[:200], "verdict": verdict,
                         "toxicity": toxicity, "spam": spam, "language": language}))
    return ModerateResponse(id=comment_id, language=language, language_confidence=confidence,
                            toxicity=toxicity, spam=spam, verdict=verdict, reasons=reasons,
                            model_versions=versions, variant=VARIANT)


@app.post("/explain")
async def explain(req: ModerateRequest) -> dict:
    return await _call("toxicity", "/explain", {"text": req.text, "top_k": 5})


@app.post("/feedback")
def feedback(req: FeedbackRequest) -> dict:
    record = {**req.model_dump(), "text": redact(req.text), "ts": datetime.now(UTC).isoformat()}
    agreed = req.predicted_verdict == req.correct_verdict
    FEEDBACK.labels(str(agreed).lower()).inc()
    if FEEDBACK_DSN:
        import psycopg2

        with psycopg2.connect(FEEDBACK_DSN) as conn, conn.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS feedback (id TEXT, text TEXT, predicted_verdict TEXT,
                   correct_verdict TEXT, moderator TEXT, ts TIMESTAMPTZ)"""
            )
            cur.execute("INSERT INTO feedback VALUES (%(id)s, %(text)s, %(predicted_verdict)s, "
                        "%(correct_verdict)s, %(moderator)s, %(ts)s)", record)
    else:
        FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        with FEEDBACK_FILE.open("a") as f:
            f.write(json.dumps(record) + "\n")
    return {"stored": True, "agreed": agreed}
