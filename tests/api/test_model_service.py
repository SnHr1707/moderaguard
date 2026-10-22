import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client_for(monkeypatch, trained_models):
    def make(task: str):
        monkeypatch.setenv("TASK", task)
        monkeypatch.setenv("MODEL_SOURCE", "local")
        import model_service

        module = importlib.reload(model_service)
        return TestClient(module.app)

    return make


def test_toxicity_predict_and_explain(client_for):
    with client_for("toxicity") as c:
        assert c.get("/ready").status_code == 200
        r = c.post("/predict", json={"texts": ["you are an idiot", "nice article"]})
        assert r.status_code == 200
        s = r.json()["scores"]
        assert s[0] > s[1]
        e = c.post("/explain", json={"text": "nice article but the author is an idiot"}).json()
        assert e["contributions"][0]["word"] == "idiot"


def test_langid_predict(client_for):
    with client_for("langid") as c:
        r = c.post("/predict", json={"texts": ["gracias por el articulo"]}).json()
        assert r["languages"] == ["es"]


def test_input_validation(client_for):
    with client_for("spam") as c:
        assert c.post("/predict", json={"texts": []}).status_code == 422


def test_metrics_endpoint(client_for):
    with client_for("spam") as c:
        c.post("/predict", json={"texts": ["hello"]})
        body = c.get("/metrics/").text
        assert "moderaguard_requests_total" in body and "moderaguard_score" in body
