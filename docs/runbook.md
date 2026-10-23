# Runbook (owner: M7, with M6)

What to do when something goes wrong, and the commands for routine operations.
Every alert in `monitoring/prometheus/alerts.yml` has a section here.

## First-time cloud setup checklist

1. Create the VM (Ubuntu 24.04, 4 vCPU, 16 GB) and open inbound ports 22, 80,
   3000, 5000, 8080, 8081 in the cloud firewall (restrict 5000/8080/8081 to your IPs).
2. `git clone` the repo on the VM, `cp .env.example .env`, set strong passwords
   and `GIT_REPO_URL`, then `sudo bash infra/cloud/setup-vm.sh`.
3. `docker compose up -d postgres s3 s3-init mlflow kafka airflow consumer`,
   then `docker compose run --rm trainer`.
4. Jenkins (`http://<VM_IP>:8081`, admin / the password from `.env`): run the
   `moderaguard` job once. The first run deploys everything, with the challenger
   as a 10% canary. In GitHub, add a webhook to `http://<VM_IP>:8081/github-webhook/`.
5. So Airflow can start canaries by itself: in Jenkins, *your user → Security →
   API token → Add*, then put `JENKINS_USER` and `JENKINS_API_TOKEN` in `.env` and
   `docker compose up -d airflow`.
6. `make k8s-monitoring`, then check Grafana at `http://<VM_IP>/grafana`.

## Routine operations

| Task | Command |
| --- | --- |
| Start a canary of the current `@challenger` | Jenkins → `moderaguard` → Build with parameters → `DEPLOY_MODE=canary-registered` |
| Shift traffic to the canary | `make canary-weight W=50` or Jenkins `DEPLOY_MODE=set-weight CANARY_WEIGHT=50` |
| Try the canary yourself | `curl -H "X-Canary: always" http://<VM_IP>/moderate -d '{"text": "..."}' -H 'Content-Type: application/json'` |
| Promote the canary | `make promote` or Jenkins `DEPLOY_MODE=promote` |
| Roll back the canary | `make rollback` or Jenkins `DEPLOY_MODE=rollback` |
| Roll back the **champion** to an older version | `python -m moderaguard.models.register set-alias --task toxicity --alias champion --version <N>` then `kubectl -n moderaguard rollout restart deployment/toxicity-svc` |
| See which versions are where | `python -m moderaguard.models.register show --task toxicity`; Grafana → *Service health* → *Loaded model versions* |
| Retrain by hand | Airflow → `retrain_dag` → Trigger |
| Re-run the drift check now | Airflow → `drift_check_dag` → Trigger |

Rolling back the champion needs no image rebuild: serving loads
`models:/moderaguard-toxicity@champion`, so moving the alias and restarting the
pods is enough. The previous champion is always tagged `@previous-champion`.

## Alerts

### ModelDriftDetected (warning, action=retrain)
More than 30% of the monitored features differ significantly from training.
This is expected after `make drift` and starts `retrain_dag` automatically.
1. Open the latest Evidently report (`reports/drift/report-*.html` on the Airflow
   host) to see which features drifted. A rise in `oov_rate` means new vocabulary.
2. Watch `retrain_dag` in Airflow. If `quality_gate` fails, the new model is
   worse or less fair: the champion stays live. Check `reports/gate_toxicity.json`.
3. If the gate passed, a canary starts through Jenkins; follow *Routine operations*.

### CanaryBlocksMuchMore (critical, action=rollback)
The canary blocks more than twice as often as stable for 10 minutes. Roll back
first (`make rollback`), then investigate with the *Verdict mix* panel and
`/explain` on a few blocked comments.

### ServiceDown / HighErrorRate / HighLatencyP95
1. `kubectl -n moderaguard get pods` and `kubectl -n moderaguard describe pod <pod>`.
2. Model services return 503 on `/ready` until their model loads. If they never
   become ready, MLflow is unreachable or the alias is missing:
   `kubectl -n moderaguard logs deploy/toxicity-svc` and check
   `MLFLOW_TRACKING_URI` in `k8s/overlays/cloud/platform.env`.
3. For latency, check the HPA: `kubectl -n moderaguard get hpa`.

### DriftCheckStale
`drift_check_dag` has not pushed for 30 minutes. Check the DAG in Airflow; the
usual causes are an empty `predictions` table (consumer not running) or the
gateway being unreachable when the reference is built.

### ModeratorDisagreementHigh
Moderators overrule more than 30% of decisions. Export the `feedback` table,
review a sample with M4, and consider retraining with the corrected labels.

### DatabaseDown / DiskAlmostFull
`docker compose ps postgres` and `docker compose logs postgres`. For disk:
`docker system prune` (old images) and remove old drift reports.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| MLflow exits at start with `No module named 'psycopg'` | MLflow 3.17 defaults to the psycopg 3 driver; the backend URI must start with `postgresql+psycopg2://` (as in `docker-compose.yml`) |
| MLflow answers `Invalid Host header` | MLflow 3 checks the Host header. Add the name or IP you use to `MLFLOW_ALLOWED_HOSTS` in `.env` |
| Model loads fail with an unpickling error | scikit-learn versions differ between training and serving. All images pin the same versions (`requirements/base.txt`); rebuild the trainer and service images together |
| Kafka clients outside Docker cannot connect | Use `localhost:29092` and set `KAFKA_EXTERNAL_HOST` to the VM IP on the cloud |
| `HTTPRoute` exists but returns 404 | The Gateway API provider is not enabled in Traefik: check `/var/lib/rancher/k3s/server/manifests/traefik-config.yaml` and `kubectl get gatewayclass` |
| Airflow tasks fail with `ModuleNotFoundError: moderaguard` | The repo is not mounted at `/opt/moderaguard` (check the `airflow` volume), or a task's `env` replaced the whole environment: keep `append_env: True` in `pipelines/airflow/dags/moderaguard_common.py` |
| Airflow DAGs never run | New DAGs start paused: switch the toggle on, or run `make demo` |
| MLflow shows only a GenAI page | MLflow 3's home page; click **Experiments** / *Model training* |
| Grafana panels say *No data* | Nothing has been sent yet: `make stream` or `make demo`, and set the time range to the last 15 minutes |
| `consumer` keeps restarting | Old image with kafka-python 3: rebuild it (`docker compose build consumer`) |
| `s3-init` shows *Exited* | Normal: it creates the S3 buckets once and stops |
| Image build fails with `Read timed out` | Slow connection: `make build` builds one image at a time and retries; run it again and it continues where it stopped |
