# Contributing

## Ground rules

- **Every change reaches `main` through a pull request** from the author's own
  GitHub account, reviewed and approved by another member. No direct pushes.
- **Push only what you own and understand.** In the viva each of us will be asked
  to explain our own folders line by line; the Git history shows who wrote what.
- One task = one GitHub issue = one branch = one PR.
- Run `make test` before opening a PR. GitHub Actions runs the same checks.

## Setting up (everyone, once)

Windows (PowerShell), with the repo outside OneDrive:

```powershell
git config --global core.autocrlf input    # keep Linux line endings (see .gitattributes)
git clone https://github.com/<org>/moderaguard.git
cd moderaguard
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
.\make.ps1 install      # pinned dependencies + the package in editable mode
.\make.ps1 pipeline     # dvc repro on the sample data (about 1 minute)
.\make.ps1 test
```

macOS / Linux: the same with `python3.12 -m venv .venv && source .venv/bin/activate`
and `make install`, `make pipeline`, `make test`.

`make.ps1` (Windows) and `Makefile` (macOS/Linux) offer the same tasks; if you add
a task to one, add it to the other.

## Branches and commits

| Branch | Purpose | Rules |
| --- | --- | --- |
| `main` | What is deployed; Jenkins deploys from here | Protected. Merges from `develop` only, at milestones; tag `v0.1`, `v0.5`, `v1.0` |
| `develop` | Integration branch | Protected. All feature PRs target it; 1 approval + green checks |
| `feature/<initials>-<task>` | One task | e.g. `feature/sp-drift-job`; delete after merge |

Commit messages follow Conventional Commits, scoped by area:

```
feat(gateway): route non-English comments to human review
fix(dvc): use the S3 endpoint from .dvc/config.local
test(fairness): BPSN AUC detects false positives on a group
docs(model-card): add intended use and limitations
```

Settings on GitHub (M1, once): Settings → Branches → add rules for `main` and
`develop`: require a pull request, 1 approval, review from Code Owners, status
checks `lint`, `tests`, `airflow-dags`, `manifests`, `docker-build`; no force pushes.
Then put everyone's GitHub username in `.github/CODEOWNERS`.

## Who pushes what, and in which order

**Step 1, day 1, M1 alone:** the shared skeleton everyone else builds on. Merge
this before anyone else opens a PR.

```
pyproject.toml  requirements/  params.yaml  Makefile  make.ps1  README.md
.gitignore  .gitattributes  .dockerignore  .env.example  .github/CODEOWNERS
.github/pull_request_template.md  .github/ISSUE_TEMPLATE/
src/moderaguard/__init__.py  src/moderaguard/config.py
docs/contracts.md  docs/CONTRIBUTING.md  tests/conftest.py
```

**Step 2, in parallel, each member's own PRs.** Split your area into 2–4 PRs
(for example "data generator", "validation", "DVC pipeline") rather than one
giant PR; small PRs are easier to review and show steady work.

| Member | Paths you commit |
| --- | --- |
| M1 Data | `src/moderaguard/data/`, `src/moderaguard/features/`, `dvc.yaml`, `.dvc/config`, `infra/seaweedfs/`, `docs/DATA.md`, `tests/data/`, `tests/unit/test_features.py` |
| M2 Streaming & orchestration | `services/producer/`, `services/consumer/`, `pipelines/airflow/`, `infra/airflow/`, `tests/unit/test_dags.py` |
| M3 Models | `src/moderaguard/models/`, `infra/mlflow/`, `infra/postgres/`, `infra/trainer/`, `tests/model/`, `tests/unit/test_langid.py` |
| M4 Responsible AI | `src/moderaguard/responsible/`, `services/moderator-ui/`, `docs/model_card.md`, `docs/fairness_report.md`, `tests/unit/test_fairness.py`, `test_quality_gate.py`, `test_redact.py` |
| M5 Services | `src/moderaguard/serving/`, `services/gateway/`, `services/model-service/`, `docker-compose.yml`, `k8s/base/`, `k8s/overlays/local/`, `scripts/load_test.py`, `tests/api/` |
| M6 CI/CD & cloud | `Jenkinsfile`, `.github/workflows/`, `infra/jenkins/`, `infra/ci/`, `infra/cloud/`, `k8s/overlays/cloud/`, `k8s/overlays/canary/`, `k8s/scripts/` |
| M7 Monitoring | `monitoring/`, `services/drift-job/`, `services/alert-bridge/`, `k8s/monitoring/`, `docs/runbook.md`, `tests/unit/test_drift.py`, `test_alert_bridge.py` |

Interdependent pieces are fine to open in parallel: build against the contracts
in [contracts.md](contracts.md), and the CI goes green once both sides are merged.

**Step 3, together:** integration on Saturday (see the demo plan), then the
`develop` → `main` merge and the `v1.0` tag.

## Make it your own: one extension per member

The baseline works end to end. Each member also builds one extension in their
area, so every part of the project has real work of its own behind it. Pick one
(or propose another) and open an issue for it.

| Member | Extension options |
| --- | --- |
| M1 | Run on the real Jigsaw + UCI data and record the results with `dvc metrics diff`; add a duplicate/near-duplicate check to validation; add a data-quality report with Evidently's `DataSummaryPreset` |
| M2 | A dead-letter topic for comments the gateway rejects; a DAG that turns moderator feedback (`feedback` table) into new training labels; consumer lag metric for Grafana |
| M3 | Tune both models with Optuna on the real data and adopt the best params; add a third challenger (e.g. complement Naive Bayes); per-class threshold tuning logged to MLflow |
| M4 | Second mitigation technique (per-group thresholds with Fairlearn's `ThresholdOptimizer`) and compare; SHAP or LIME explanations next to the occlusion method; fairness metrics pushed to Prometheus |
| M5 | Response caching for repeated comments; batch endpoint `/moderate/batch`; readiness that checks the model version matches the registry alias |
| M6 | Automatic canary analysis in Jenkins (query Prometheus, promote or roll back by itself); signed images with cosign; deploy a second environment (staging namespace) |
| M7 | A Grafana alert panel and notification channel (email/Telegram); per-feature drift dashboard with the Evidently HTML report linked; SLO and error-budget panels |

## Pull request checklist

The PR template asks for this; reviewers check it.

- [ ] Linked issue (`Closes #12`)
- [ ] Tests added or updated, `make test` passes
- [ ] Contracts unchanged, or both sides approved the change
- [ ] No secrets, data files or model files in the diff
- [ ] Docs or README updated if behaviour changed
