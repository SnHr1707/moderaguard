"""Alert bridge: turns Alertmanager alerts into an Airflow retraining run (owner: M7).

Alertmanager can only send its own JSON format to a webhook, and the Airflow 3
REST API expects a different body plus a JWT token (POST /auth/token, then
POST /api/v2/dags/<dag>/dagRuns), so this small service sits in between. It also enforces a cooldown so one drift episode starts one
retraining, not one per alert repeat.

Env: AIRFLOW_URL [http://airflow:8080], AIRFLOW_USER [admin], AIRFLOW_PASSWORD [admin],
     RETRAIN_DAG [retrain_dag], COOLDOWN_MINUTES [60]
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import FastAPI, Request

AIRFLOW_URL = os.environ.get("AIRFLOW_URL", "http://airflow:8080")
AUTH = (os.environ.get("AIRFLOW_USER", "admin"), os.environ.get("AIRFLOW_PASSWORD", "admin"))
DAG = os.environ.get("RETRAIN_DAG", "retrain_dag")
COOLDOWN = timedelta(minutes=int(os.environ.get("COOLDOWN_MINUTES", 60)))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("alert-bridge")
app = FastAPI(title="ModeraGuard alert bridge")
state: dict = {"last_trigger": None}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "last_trigger": state["last_trigger"].isoformat() if state["last_trigger"] else None}


@app.post("/alert")
async def alert(request: Request) -> dict:
    body = await request.json()
    firing = [a for a in body.get("alerts", [])
              if a.get("status") == "firing" and a.get("labels", {}).get("action") == "retrain"]
    if not firing:
        return {"triggered": False, "reason": "no firing retrain alerts"}

    now = datetime.now(UTC)
    if state["last_trigger"] and now - state["last_trigger"] < COOLDOWN:
        return {"triggered": False, "reason": f"cooldown until {(state['last_trigger'] + COOLDOWN).isoformat()}"}

    alert_names = sorted({a["labels"].get("alertname", "?") for a in firing})
    payload = {"dag_run_id": f"drift-{now.strftime('%Y%m%dT%H%M%S')}", "logical_date": None,
               "conf": {"reason": ",".join(alert_names), "triggered_at": now.isoformat()}}
    async with httpx.AsyncClient(timeout=10) as client:
        token_r = await client.post(f"{AIRFLOW_URL}/auth/token", json={"username": AUTH[0], "password": AUTH[1]})
        if token_r.status_code >= 300:
            log.error("Airflow login failed: %s %s", token_r.status_code, token_r.text)
            return {"triggered": False, "reason": f"airflow login returned {token_r.status_code}"}
        headers = {"Authorization": f"Bearer {token_r.json()['access_token']}"}
        r = await client.post(f"{AIRFLOW_URL}/api/v2/dags/{DAG}/dagRuns", json=payload, headers=headers)
    if r.status_code >= 300:
        log.error("Airflow refused the trigger: %s %s", r.status_code, r.text)
        return {"triggered": False, "reason": f"airflow returned {r.status_code}"}
    state["last_trigger"] = now
    log.info("started %s run %s because of %s", DAG, payload["dag_run_id"], alert_names)
    return {"triggered": True, "dag_run_id": payload["dag_run_id"]}
