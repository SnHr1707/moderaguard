# MLflow tracking server + registry (owner: M3).
# Metadata in Postgres, model artifacts in S3 (SeaweedFS).
FROM python:3.12-slim
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN --mount=type=cache,target=/root/.cache/pip pip install mlflow==3.17.1 psycopg2-binary==2.9.13 "boto3>=1.34,<2"
EXPOSE 5000
# --allowed-hosts: MLflow 3 rejects unknown Host headers; list every name clients use.
CMD ["sh", "-c", "mlflow server --host 0.0.0.0 --port 5000 \
  --backend-store-uri \"$MLFLOW_BACKEND_STORE_URI\" \
  --artifacts-destination \"$MLFLOW_ARTIFACTS_DESTINATION\" \
  --allowed-hosts \"${MLFLOW_ALLOWED_HOSTS:-mlflow,mlflow:5000,localhost,localhost:5000,127.0.0.1:5000}\""]
