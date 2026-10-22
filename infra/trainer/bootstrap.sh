#!/usr/bin/env sh
# Bootstrap a fresh stack: build data, train every model, audit, register.
# Runs inside the trainer container with the repo mounted at /workspace.
set -eu
cd /workspace

echo "== 1/5 data"
[ -f data/sample/jigsaw/all_data.csv ] || python -m moderaguard.data.make_sample
python -m moderaguard.data.prepare
python -m moderaguard.data.validate

echo "== 2/5 training"
python -m moderaguard.models.train --task toxicity --variant champion
python -m moderaguard.models.train --task toxicity --variant champion --no-mitigation
python -m moderaguard.models.train --task toxicity --variant challenger
python -m moderaguard.models.train --task spam
python -m moderaguard.models.train --task langid

echo "== 3/5 fairness audit"
python -m moderaguard.responsible.fairness --variant champion champion_unmitigated challenger

echo "== 4/5 quality gate (challenger vs champion)"
python -m moderaguard.responsible.quality_gate --task toxicity --candidate challenger --baseline champion || \
  echo "challenger did not pass the gate; it will be registered but not promoted"

echo "== 5/5 registry"
python -m moderaguard.models.register register --task toxicity --variant champion --alias champion
python -m moderaguard.models.register register --task toxicity --variant challenger --alias challenger
python -m moderaguard.models.register register --task spam --variant champion --alias champion
python -m moderaguard.models.register register --task langid --variant champion --alias champion
echo "bootstrap complete: models are in MLflow at $MLFLOW_TRACKING_URI"
