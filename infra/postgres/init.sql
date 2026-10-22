-- One Postgres instance, three databases (owner: M3).
-- mlflow: tracking + registry metadata; airflow: Airflow metadata;
-- moderaguard: prediction log (consumer) and moderator feedback (gateway).
CREATE DATABASE mlflow;
CREATE DATABASE airflow;
