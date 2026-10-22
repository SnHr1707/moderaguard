"""Kafka consumer: moderates streamed comments and logs predictions (owner: M2).

comments.incoming -> gateway /moderate -> predictions.out + Postgres `predictions` table

The predictions table is what M7's drift job reads. Only redacted text is stored.

Env: KAFKA_BOOTSTRAP [kafka:9092], GATEWAY_URL [http://gateway:8000],
     PREDICTIONS_DSN [postgresql://moderaguard:moderaguard@postgres:5432/moderaguard]
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime

import httpx
import psycopg2
from kafka import KafkaConsumer, KafkaProducer

# KafkaError covers kafka-python 2 (NoBrokersAvailable) and 3 (KafkaTimeoutError)
from kafka.errors import KafkaError

from moderaguard.responsible.redact import redact

IN_TOPIC, OUT_TOPIC = "comments.incoming", "predictions.out"
DDL = """
CREATE TABLE IF NOT EXISTS predictions (
    id TEXT PRIMARY KEY,
    text TEXT,
    source TEXT,
    language TEXT,
    toxicity DOUBLE PRECISION,
    spam DOUBLE PRECISION,
    verdict TEXT,
    toxicity_model TEXT,
    variant TEXT,
    ts TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS predictions_ts ON predictions (ts DESC);
"""


def connect_kafka(bootstrap: str):
    for attempt in range(30):
        try:
            consumer = KafkaConsumer(IN_TOPIC, bootstrap_servers=bootstrap, group_id="moderaguard-consumer",
                                     value_deserializer=lambda v: json.loads(v.decode()),
                                     auto_offset_reset="earliest", enable_auto_commit=True)
            producer = KafkaProducer(bootstrap_servers=bootstrap, value_serializer=lambda v: json.dumps(v).encode())
            return consumer, producer
        except KafkaError:
            print(f"[consumer] Kafka not ready ({attempt + 1}/30), retrying in 2s")
            time.sleep(2)
    raise SystemExit("[consumer] could not connect to Kafka")


def connect_db(dsn: str):
    for attempt in range(30):
        try:
            conn = psycopg2.connect(dsn)
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(DDL)
            return conn
        except psycopg2.OperationalError:
            print(f"[consumer] Postgres not ready ({attempt + 1}/30), retrying in 2s")
            time.sleep(2)
    raise SystemExit("[consumer] could not connect to Postgres")


def main() -> None:
    gateway = os.environ.get("GATEWAY_URL", "http://gateway:8000")
    consumer, producer = connect_kafka(os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092"))
    conn = connect_db(os.environ.get("PREDICTIONS_DSN",
                                     "postgresql://moderaguard:moderaguard@postgres:5432/moderaguard"))
    http = httpx.Client(timeout=10)
    print(f"[consumer] reading {IN_TOPIC}, calling {gateway}")

    for n, message in enumerate(consumer, start=1):
        msg = message.value
        try:
            r = http.post(f"{gateway}/moderate", json={"text": msg["text"], "id": msg["id"]})
            r.raise_for_status()
            result = r.json()
        except httpx.HTTPError as e:
            print(f"[consumer] gateway error for {msg['id']}: {e}")
            continue
        out = {**result, "source": msg.get("source"), "ts": datetime.now(UTC).isoformat()}
        producer.send(OUT_TOPIC, value=out)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO predictions VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (id) DO NOTHING""",
                (result["id"], redact(msg["text"]), msg.get("source"), result["language"], result["toxicity"],
                 result["spam"], result["verdict"], result["model_versions"].get("toxicity"),
                 result["variant"], out["ts"]),
            )
        if n % 100 == 0:
            print(f"[consumer] processed {n}")


if __name__ == "__main__":
    main()
