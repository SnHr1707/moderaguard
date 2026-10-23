# Demo script (about 15 minutes, 2 minutes per member)

Set up 30 minutes before (Windows: `.\make.ps1 …`):

1. `make up` and `make bootstrap` (first time, or after updating the code)
2. `make demo`: streams comments, sends a few hundred requests and some
   moderator feedback, switches on the Airflow pipelines and runs a
   hyperparameter search, so every tool has something to show
3. open the tabs below and keep the backup video ready
4. for item 8, run `make demo-drift` live: it switches to the newer comments and
   reports each step (drift check → alert → retrain_dag) as it happens

Where to look in each tool:

| Tool | Click |
| --- | --- |
| MLflow 3 | it opens on a GenAI page: choose **Experiments** (or *Model training*) → `moderaguard-toxicity`; compare runs; **Models** for the registry and aliases. A run's *Artifacts* tab has the ROC curve, confusion matrix and top n-grams |
| Airflow | **Dags** → a DAG → **Graph**; click a box → **Logs** |
| Grafana | **Dashboards** → *ModeraGuard*; time range *Last 15 minutes* |
| Prometheus | **Status → Target health** (all up), **Alerts** |
| Alertmanager | empty until `demo-drift`; then `ModelDriftDetected` |
| Moderator console | http://localhost:8501, the *System* tab links everything |

Tabs: GitHub repo · MLflow · Airflow · Grafana (*Models, canary and drift*) ·
Jenkins · moderator UI · a terminal.

| # | Who | Show | Say |
| --- | --- | --- | --- |
| 1 | M1 | Repo, Projects board, Insights → Contributors, `dvc dag`, then `dvc repro` (nothing to do) | Every change went through a reviewed PR; DVC knows which data and parameters produced which model |
| 2 | M1 | Corrupt a label in a processed file → `python -m moderaguard.data.validate` fails | Bad data stops the pipeline before training |
| 3 | M2 | Airflow DAG graphs; producer and consumer logs | Comments arrive through Kafka; Airflow schedules drift checks and retraining |
| 4 | M3 | MLflow: experiments, the Optuna trials, the registry with `champion` / `challenger` | Serving loads models by alias, so promotion is an alias move, not a rebuild |
| 5 | M5 | `kubectl get pods`, a request in Swagger, `make load-test` while watching the HPA | Gateway calls three model services; the language check comes first |
| 6 | M4 | UI on a toxic and a harmless comment with an identity term; explanation chart; fairness report; redacted log line | Masking identity terms cut the worst false-positive gap from 0.68 to 0.00 for 0.005 AUC |
| 7 | M6 | A small PR → Actions green → merge → Jenkins stages → canary at 10%; `curl -H "X-Canary: always"` | Nothing reaches users without tests, the quality gate and a security scan |
| 8 | M7 | `make drift` → drift panel crosses the line → alert fires → `retrain_dag` starts | The system notices new slang and retrains itself |
| 9 | All | Retrained model passes the gate → becomes the canary → `make promote` | The loop is closed |

## Questions to rehearse

Everyone should be able to answer 1–3, not only the owner.

1. Why Kafka instead of calling the gateway directly? (buffering bursts, replay, decoupling the producer from the model's speed)
2. How do you know the drift is real and not noise? (statistical tests per feature at p < 0.05, a share threshold, a window of 1,000 comments, and a control sample that shows 0% drift)
3. What happens if the new model is more accurate but less fair? (the gate rejects it; show `test_more_accurate_but_less_fair_model_fails`)
4. Why does the gateway check the language first? (the models are English-only; scoring other languages would be unreliable, so they go to humans)
5. How do you roll back a bad model without downtime? (move the alias, restart pods one by one; or end the canary)
6. Why DVC when the data is already on Kaggle? (exact reproducibility: the processed data, models and metrics of every commit are recoverable)
7. Why is the test set kept fixed during retraining? (otherwise comments the old model trained on would leak into the test set and make the old model look better than it is)
