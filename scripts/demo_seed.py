"""Fill every tool with real activity before a demo (owner: M5).

Runs inside the toolbox container (no Python needed on your laptop):
  .\\make.ps1 demo         ->  python scripts/demo_seed.py
  .\\make.ps1 demo-drift   ->  python scripts/demo_seed.py --drift

Normal mode:
  1. waits until the gateway is ready and checks MLflow has trained models
  2. sends a few hundred real comments through the gateway (Grafana, Prometheus)
  3. sends moderator feedback, some of it disagreeing (agreement panel)
  4. switches on the Airflow pipelines and starts ingest_dag and drift_check_dag

Drift mode (after `.\\make.ps1 drift` has streamed the newer comments for a minute):
  starts drift_check_dag, then follows the chain: drift alert in Prometheus ->
  Alertmanager -> alert bridge -> a retrain_dag run in Airflow.

Uses only httpx and the standard library, so it runs in the gateway image.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

EXTRA = [
    "Subscribe to my channel for free gift cards http://bit.ly/9999",
    "Check out my page, I just reached 1000 subscribers!!!",
    "Make money fast working from home, visit www.cashnow123.com",
    "Muy buen articulo, gracias por compartir",
    "Je ne suis pas d'accord avec cet article",
    "Email me at someone@example.com, the author is a moron",
]
DAGS = ["ingest_dag", "drift_check_dag", "retrain_dag"]


def say(msg: str) -> None:
    print(msg, flush=True)


def wait_for(client: httpx.Client, name: str, url: str, timeout: int = 300) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            if client.get(url).status_code < 400:
                say(f"  ok  {name}")
                return True
        except httpx.HTTPError:
            pass
        time.sleep(5)
    say(f"  !!  {name} not ready after {timeout}s ({url})")
    return False


def load_comments(path: Path, n: int, seed: int = 7) -> list[str]:
    rows = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            rows = [r["comment_text"] for r in csv.DictReader(f) if r.get("comment_text")]
    rng = random.Random(seed)
    picked = rng.sample(rows, min(n, len(rows))) if rows else []
    return picked + EXTRA * max(1, n // 60)


# ----------------------------------------------------------------- Airflow
class Airflow:
    def __init__(self, client: httpx.Client, url: str, user: str, password: str):
        self.c, self.url = client, url.rstrip("/")
        r = self.c.post(f"{self.url}/auth/token", json={"username": user, "password": password})
        r.raise_for_status()
        self.h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    def unpause(self, dag: str) -> bool:
        r = self.c.patch(f"{self.url}/api/v2/dags/{dag}", json={"is_paused": False}, headers=self.h)
        return r.status_code < 300

    def trigger(self, dag: str) -> str | None:
        r = self.c.post(f"{self.url}/api/v2/dags/{dag}/dagRuns", json={"logical_date": None}, headers=self.h)
        return r.json().get("dag_run_id") if r.status_code < 300 else None

    def runs(self, dag: str) -> list[dict]:
        r = self.c.get(f"{self.url}/api/v2/dags/{dag}/dagRuns", params={"order_by": "-start_date", "limit": 5},
                       headers=self.h)
        return r.json().get("dag_runs", []) if r.status_code < 300 else []


def airflow_client(client: httpx.Client, args) -> Airflow | None:
    for _ in range(24):  # Airflow standalone takes a while on first start
        try:
            return Airflow(client, args.airflow, args.airflow_user, args.airflow_password)
        except httpx.HTTPError:
            time.sleep(5)
    say("  !!  could not log in to Airflow; open it once in the browser, then run this again")
    return None


# ----------------------------------------------------------------- modes
def normal(args, client: httpx.Client) -> int:
    say("1/4  Waiting for services")
    if not wait_for(client, "gateway", f"{args.gateway}/ready"):
        say("     The model services load their models from MLflow. Has `.\\make.ps1 bootstrap` finished?")
        return 1
    r = client.get(f"{args.mlflow}/api/2.0/mlflow/registered-models/alias",
                   params={"name": "moderaguard-toxicity", "alias": "champion"})
    if r.status_code != 200:
        say("  !!  No toxicity champion in MLflow. Run `.\\make.ps1 bootstrap` first.")
        return 1
    say(f"  ok  MLflow champion = toxicity version {r.json()['model_version']['version']}")

    comments = load_comments(Path(args.comments_csv), args.comments)
    say(f"2/4  Sending {len(comments)} comments through the gateway")
    verdicts, results = Counter(), []

    def send(text: str):
        try:
            res = client.post(f"{args.gateway}/moderate", json={"text": text}).json()
            return text, res
        except (httpx.HTTPError, ValueError):
            return text, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        for i, (text, res) in enumerate(pool.map(send, comments), 1):
            if res and "verdict" in res:
                verdicts[res["verdict"]] += 1
                results.append((text, res))
            if i % 100 == 0:
                say(f"     {i} sent")
    say(f"  ok  verdicts: {dict(verdicts)}")

    say(f"3/4  Sending {args.feedback} moderator feedback entries")
    rng = random.Random(1)
    for text, res in rng.sample(results, min(args.feedback, len(results))):
        correct = res["verdict"]
        if rng.random() < 0.2:  # moderators overrule about one decision in five
            correct = rng.choice([v for v in ("allow", "review", "block") if v != correct])
        client.post(f"{args.gateway}/feedback", json={"id": res["id"], "text": text, "predicted_verdict":
                                                      res["verdict"], "correct_verdict": correct,
                                                      "moderator": "demo"})
    say("  ok  feedback stored")

    say("4/4  Airflow: switching on the pipelines")
    af = airflow_client(client, args)
    if af:
        for dag in DAGS:
            say(f"  {'ok' if af.unpause(dag) else '!!'}  {dag} unpaused")
        for dag in ("ingest_dag", "drift_check_dag"):
            run = af.trigger(dag)
            say(f"  {'ok' if run else '!!'}  {dag} started {run or ''}")

    say("\nDone. Open the moderator console at http://localhost:8501 (System tab lists every tool).")
    say("Grafana shows the traffic within a minute; Airflow runs take 1-3 minutes.")
    return 0


def drift(args, client: httpx.Client) -> int:
    af = airflow_client(client, args)
    if not af:
        return 1
    for dag in DAGS:
        af.unpause(dag)
    say("1/3  Starting drift_check_dag (compares recent comments with the training data)")
    before = {r["dag_run_id"] for r in af.runs("retrain_dag")}
    run = af.trigger("drift_check_dag")
    say(f"  ok  {run}" if run else "  !!  could not start drift_check_dag")

    say("2/3  Waiting for Prometheus to fire ModelDriftDetected (up to 5 minutes)")
    deadline, fired = time.time() + 300, False
    while time.time() < deadline and not fired:
        try:
            alerts = client.get(f"{args.prometheus}/api/v1/alerts").json()["data"]["alerts"]
            fired = any(a["labels"].get("alertname") == "ModelDriftDetected" and a["state"] == "firing"
                        for a in alerts)
        except (httpx.HTTPError, ValueError, KeyError):
            pass
        if not fired:
            time.sleep(10)
    if not fired:
        say("  !!  no drift alert yet. Check the drift_check_dag logs in Airflow; it needs 100+ streamed "
            "comments, so let `.\\make.ps1 drift` run a little longer and try again.")
        return 1
    say("  ok  ModelDriftDetected is firing (see Prometheus → Alerts and Alertmanager)")

    say("3/3  Waiting for the alert bridge to start retrain_dag (up to 3 minutes)")
    deadline = time.time() + 180
    while time.time() < deadline:
        new = [r for r in af.runs("retrain_dag") if r["dag_run_id"] not in before]
        if new:
            say(f"  ok  retrain_dag run {new[0]['dag_run_id']} is {new[0]['state']}. Follow it in Airflow "
                "(Graph view); when it succeeds MLflow has a new challenger version.")
            return 0
        time.sleep(10)
    say("  !!  retrain_dag has not started. Check `docker compose logs alert-bridge`.")
    return 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--drift", action="store_true", help="run the drift -> alert -> retraining scenario")
    p.add_argument("--gateway", default="http://gateway:8000")
    p.add_argument("--mlflow", default="http://mlflow:5000")
    p.add_argument("--airflow", default="http://airflow:8080")
    p.add_argument("--prometheus", default="http://prometheus:9090")
    p.add_argument("--airflow-user", default="admin")
    p.add_argument("--airflow-password", default="admin")
    p.add_argument("--comments", type=int, default=400)
    p.add_argument("--feedback", type=int, default=40)
    p.add_argument("--comments-csv", default="/data/sample/jigsaw/all_data.csv")
    args = p.parse_args()
    # MLflow 3 checks the Host header; "mlflow:5000" is in its allowed list
    with httpx.Client(timeout=20) as client:
        return drift(args, client) if args.drift else normal(args, client)


if __name__ == "__main__":
    sys.exit(main())
