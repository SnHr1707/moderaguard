"""Gateway tests with the three model services mocked out (no network needed)."""

import httpx
import pytest
from fastapi.testclient import TestClient

import gateway

FAKE = {
    "toxicity": {"idiot": 0.95, "dumb": 0.6},
    "spam": {"subscribe": 0.97},
}


def _handler(request: httpx.Request) -> httpx.Response:
    body = request.read().decode()
    import json

    payload = json.loads(body) if body else {}
    host = request.url.host
    if request.url.path == "/ready":
        return httpx.Response(200, json={"status": "ready"})
    if host == "langid-svc":
        text = payload["texts"][0]
        lang = "es" if "gracias" in text else "en"
        return httpx.Response(200, json={"languages": [lang], "confidences": [0.9], "model_version": "lid-1"})
    task = "toxicity" if host == "toxicity-svc" else "spam"
    if request.url.path == "/explain":
        return httpx.Response(200, json={"score": 0.9, "contributions": [{"word": "idiot", "contribution": 0.8}]})
    text = payload["texts"][0].lower()
    score = max((v for k, v in FAKE[task].items() if k in text), default=0.05)
    return httpx.Response(200, json={"scores": [score], "model_version": f"{task}-1"})


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(gateway, "FEEDBACK_FILE", tmp_path / "feedback.jsonl")
    gateway.state["client"] = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    with TestClient(gateway.app) as c:
        yield c


def test_clean_comment_is_allowed(client):
    r = client.post("/moderate", json={"text": "Lovely article"}).json()
    assert r["verdict"] == "allow" and r["language"] == "en"
    assert set(r["model_versions"]) == {"langid", "toxicity", "spam"}


def test_toxic_comment_is_blocked(client):
    r = client.post("/moderate", json={"text": "you idiot"}).json()
    assert r["verdict"] == "block" and "toxic" in r["reasons"]


def test_borderline_goes_to_review(client):
    assert client.post("/moderate", json={"text": "that is dumb"}).json()["verdict"] == "review"


def test_spam_is_blocked(client):
    r = client.post("/moderate", json={"text": "subscribe to my channel"}).json()
    assert r["verdict"] == "block" and "spam" in r["reasons"]


def test_other_languages_go_to_human_review(client):
    r = client.post("/moderate", json={"text": "gracias amigo"}).json()
    assert r["verdict"] == "review" and r["toxicity"] is None
    assert r["reasons"] == ["unsupported_language:es"]


def test_feedback_is_redacted(client, tmp_path):
    r = client.post("/feedback", json={"id": "1", "text": "email me a@b.com", "predicted_verdict": "block",
                                       "correct_verdict": "allow"})
    assert r.json() == {"stored": True, "agreed": False}
    assert "a@b.com" not in (tmp_path / "feedback.jsonl").read_text()


def test_decide_is_pure():
    assert gateway.decide(0.1, 0.1, "en") == ("allow", [])
    assert gateway.decide(0.9, 0.95, "en") == ("block", ["toxic", "spam"])
    assert gateway.decide(0.1, 0.7, "en") == ("review", ["possibly_spam"])
