# Common commands. `make help` lists them.
.DEFAULT_GOAL := help
SHELL := /bin/bash
PY ?= python
CLUSTER ?= moderaguard

help: ## show this list
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- development
install: ## install everything into the active Python 3.12 virtualenv
	pip install -r requirements/dev.txt && pip install --no-deps -e .

sample: ## generate the synthetic sample datasets
	$(PY) -m moderaguard.data.make_sample

pipeline: ## run the whole DVC pipeline (data -> train -> fairness -> gate)
	dvc repro

test: ## run lint + all tests
	ruff check .
	pytest

fairness: ## print the fairness report
	@cat reports/fairness_report.md

tune: ## Optuna search for the toxicity model (logged to MLflow)
	$(PY) -m moderaguard.models.tune --task toxicity

dashboards: ## regenerate Grafana dashboard JSON
	$(PY) monitoring/grafana/build_dashboards.py

# ------------------------------------------------------------- docker compose
# Built one after another: building all images at once on a slow connection makes pip time out.
# (spam-svc and langid-svc reuse the model-service image built for toxicity-svc)
BUILD_ORDER := mlflow toxicity-svc gateway moderator-ui consumer alert-bridge airflow

build: ## build the images one at a time
	@test -f .env || cp .env.example .env
	for svc in $(BUILD_ORDER); do docker compose build $$svc || exit 1; done

up: build ## build and start the full local stack
	docker compose up -d

bootstrap: ## train + register the first models in MLflow (run once after `make up`)
	docker compose --profile setup build trainer
	docker compose run --rm trainer

stream: ## stream training-era comments through Kafka
	PRODUCER_MODE=baseline docker compose --profile stream up -d --force-recreate producer

drift: ## stream the newer comments (causes drift -> alert -> retraining)
	PRODUCER_MODE=drift docker compose --profile stream up -d --force-recreate producer

down: ## stop the stack (keeps data)
	docker compose --profile stream --profile setup down

clean: ## stop the stack and delete all its data
	docker compose --profile stream --profile setup down -v

logs: ## follow the logs of the serving services
	docker compose logs -f gateway toxicity-svc spam-svc langid-svc consumer

smoke: ## send two comments to the gateway
	curl -s -X POST localhost:8000/moderate -H 'Content-Type: application/json' -d '{"text": "Thanks, great article"}'; echo
	curl -s -X POST localhost:8000/moderate -H 'Content-Type: application/json' -d '{"text": "You are a complete idiot"}'; echo

load-test: ## 2000 requests to the gateway (watch the HPA scale on Kubernetes)
	$(PY) scripts/load_test.py --url $${URL:-http://localhost:8000} --requests 2000 --concurrency 20

# ----------------------------------------------------------------- kubernetes
kind-up: ## create a local kind cluster and load the images built by `make up`
	kind create cluster --name $(CLUSTER) || true
	for img in model-service gateway moderator-ui; do kind load docker-image moderaguard/$$img:local --name $(CLUSTER); done

k8s-local: ## deploy the serving stack to kind
	kubectl apply -k k8s/overlays/local
	kubectl -n moderaguard rollout status deployment/gateway --timeout=180s

k8s-cloud: ## deploy the serving stack to the cloud cluster
	kubectl apply -k k8s/overlays/cloud

k8s-canary: ## start a 10% canary of the toxicity challenger
	kubectl apply -k k8s/overlays/canary
	k8s/scripts/set-canary-weight.sh 10

canary-weight: ## make canary-weight W=50
	k8s/scripts/set-canary-weight.sh $(W)

promote: ## challenger -> champion, end the canary
	k8s/scripts/end-canary.sh promote

rollback: ## remove the canary, keep the champion
	k8s/scripts/end-canary.sh rollback

k8s-monitoring: ## Prometheus, Alertmanager, Grafana, alert bridge on the cluster
	kubectl kustomize --load-restrictor LoadRestrictionsNone k8s/monitoring | kubectl apply -f -

.PHONY: help install sample pipeline test fairness tune dashboards build up bootstrap stream drift down clean logs smoke \
	load-test kind-up k8s-local k8s-cloud k8s-canary canary-weight promote rollback k8s-monitoring
