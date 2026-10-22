import httpx
import pytest
from fastapi.testclient import TestClient

import bridge

FIRING = {"alerts": [{"status": "firing", "labels": {"alertname": "ModelDriftDetected", "action": "retrain"}}]}


@pytest.fixture()
def client(monkeypatch):
    calls = []

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json, headers=None):
            if url.endswith("/auth/token"):
                return httpx.Response(201, json={"access_token": "jwt"})
            calls.append((url, json, headers))
            return httpx.Response(200, json={"state": "queued"})

    monkeypatch.setattr(bridge.httpx, "AsyncClient", FakeClient)
    bridge.state["last_trigger"] = None
    return TestClient(bridge.app), calls


def test_firing_drift_alert_triggers_retraining(client):
    c, calls = client
    r = c.post("/alert", json=FIRING).json()
    assert r["triggered"] and calls[0][0].endswith("/api/v2/dags/retrain_dag/dagRuns")
    assert calls[0][2] == {"Authorization": "Bearer jwt"}


def test_cooldown_prevents_duplicate_runs(client):
    c, calls = client
    c.post("/alert", json=FIRING)
    assert not c.post("/alert", json=FIRING).json()["triggered"]
    assert len(calls) == 1


def test_resolved_or_unrelated_alerts_are_ignored(client):
    c, calls = client
    resolved = {"alerts": [{"status": "resolved", "labels": {"action": "retrain"}}]}
    other = {"alerts": [{"status": "firing", "labels": {"alertname": "HighLatency"}}]}
    assert not c.post("/alert", json=resolved).json()["triggered"]
    assert not c.post("/alert", json=other).json()["triggered"]
    assert calls == []
