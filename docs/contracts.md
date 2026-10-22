# Interface contracts

These are the agreements between the seven parts of the system. Each one has a
producer and a consumer; as long as both sides keep to the contract, the owners
can work in parallel. **Change a contract only in a pull request reviewed by
both sides.**

| Contract | Producer → consumer | Shape | Defined in |
| --- | --- | --- | --- |
| Processed toxicity data | M1 → M3, M4 | Parquet: `id` (int), `comment_text` (str), `created_date` (UTC datetime), `toxic` (0/1, Jigsaw score ≥ 0.5), identity columns in [0, 1] (`male`, `female`, `homosexual_gay_or_lesbian`, `christian`, `jewish`, `muslim`, `black`, `white`, `psychiatric_or_mental_illness`) | `data/validate.py::toxicity_schema` |
| Processed spam data | M1 → M3 | Parquet: `id` (str), `text` (str), `spam` (0/1) | `data/validate.py::spam_schema` |
| Drift stream | M1 → M2 | `toxicity_stream.parquet`: comments dated on/after `data.drift_split_date`, same columns as above | `data/prepare.py` |
| Model objects | M3 → M5 | `TextScorer.score(texts) -> list[float]` (probability of the positive class); `LangId.detect(texts) -> list[(language, confidence)]` | `models/core.py` |
| Model registry | M3 → M5, M6 | Registered models `moderaguard-toxicity`, `moderaguard-spam`, `moderaguard-langid`; aliases `champion` (stable traffic) and `challenger` (canary) | `config.py`, `models/register.py` |
| Quality gate | M4 → M6, M2 | `python -m moderaguard.responsible.quality_gate --task toxicity --candidate X --baseline Y` exits 0 = pass, 1 = fail; writes `reports/gate_toxicity.json` | `responsible/quality_gate.py` |
| Redaction | M4 → M2, M5 | `redact(text) -> str`; masks e-mails, URLs, phone numbers and @handles. Call it before any comment text is logged or stored | `responsible/redact.py` |
| Model service API | M5 internal | `POST /predict {"texts": [str]}` → `{"scores": [float], "model_version": str}` (langid: `{"languages", "confidences", "model_version"}`); `POST /explain {"text"}`; `GET /health`, `/ready`; `POST /reload` | `services/model-service/` |
| Gateway API | M5 → M2, M4, M7 | `POST /moderate {"text": str, "id"?: str}` → `{"id", "language", "language_confidence", "toxicity", "spam", "verdict": "allow"\|"review"\|"block", "reasons": [str], "model_versions": {...}, "variant": "stable"\|"canary"}`; `POST /explain`; `POST /feedback` | `services/gateway/gateway.py` |
| Kafka topics | M2 | `comments.incoming`: `{id, text, source, ts}`; `predictions.out`: gateway response + `source`, `ts` | `services/producer/`, `services/consumer/` |
| Prediction log | M2 → M7 | Postgres table `predictions(id, text [redacted], source, language, toxicity, spam, verdict, toxicity_model, variant, ts)` | `services/consumer/consumer.py` |
| Metrics | M5 → M7 | `moderaguard_requests_total{service,variant,endpoint,status}`, `moderaguard_latency_seconds{service,variant,endpoint}`, `moderaguard_score{model,variant}`, `moderaguard_verdicts_total{verdict,variant,reason}`, `moderaguard_languages_total{language}`, `moderaguard_feedback_total{agreed}`, `moderaguard_model_info{service,variant,version}` | `serving/metrics.py` |
| Drift metrics | M7 | Pushed to the Pushgateway as job `moderaguard-drift`: `moderaguard_drift_share`, `moderaguard_drift_p_value{feature}`, `moderaguard_drift_window_size`, `moderaguard_drift_last_run_timestamp` | `services/drift-job/drift.py` |
| Retrain trigger | M7 → M2 | Alerts labelled `action="retrain"` → Alertmanager → `POST alert-bridge:8090/alert` → Airflow `POST /api/v2/dags/retrain_dag/dagRuns` (JWT from `/auth/token`), at most once per `COOLDOWN_MINUTES` | `monitoring/alertmanager/`, `services/alert-bridge/` |
| Canary deploy | M2 → M6 | Airflow calls Jenkins `buildWithParameters?DEPLOY_MODE=canary-registered`; Jenkins deploys whatever `@challenger` points at | `pipelines/airflow/dags/retrain_dag.py`, `Jenkinsfile` |
| Settings | everyone | All thresholds and hyperparameters live in `params.yaml`; DVC re-runs the stages that depend on a changed section | `params.yaml` |
