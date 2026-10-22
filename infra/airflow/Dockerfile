# Airflow image for ModeraGuard (owner: M2).
# The ML code gets its own virtualenv (/opt/ml-venv) so scikit-learn, MLflow and
# Evidently never conflict with Airflow's own pinned dependencies.
FROM apache/airflow:3.3.2-python3.12
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10 PIP_DISABLE_PIP_VERSION_CHECK=1

USER root
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/ml-venv && chown -R airflow:0 /opt/ml-venv
USER airflow

COPY infra/airflow/requirements-ml.txt /tmp/requirements-ml.txt
RUN --mount=type=cache,target=/home/airflow/.cache/pip,uid=50000 /opt/ml-venv/bin/pip install -r /tmp/requirements-ml.txt

# The repository itself is mounted at /opt/moderaguard (see docker-compose.yml);
# pointing PYTHONPATH at its src/ means code changes need no image rebuild.
ENV PYTHONPATH=/opt/moderaguard/src
