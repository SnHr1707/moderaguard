"""Kafka producer: replays comments into `comments.incoming` (owner: M2).

Two modes:
  --mode baseline  comments from before the drift date (what the model was trained on)
  --mode drift     comments from after the drift date (newer slang -> real drift)

Run:  python services/producer/producer.py --mode baseline --rate 5
Env:  KAFKA_BOOTSTRAP [kafka:9092], DATA_DIR [data/processed]
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from kafka import KafkaProducer

# KafkaError covers kafka-python 2 (NoBrokersAvailable) and 3 (KafkaTimeoutError)
from kafka.errors import KafkaError

TOPIC = "comments.incoming"


def load_comments(mode: str, data_dir: Path) -> pd.DataFrame:
    name = "toxicity_test.parquet" if mode == "baseline" else "toxicity_stream.parquet"
    df = pd.read_parquet(data_dir / name, columns=["id", "comment_text"])
    return df.sample(frac=1.0, random_state=0) if mode == "baseline" else df


def connect(bootstrap: str, retries: int = 30) -> KafkaProducer:
    for attempt in range(retries):
        try:
            return KafkaProducer(bootstrap_servers=bootstrap,
                                 value_serializer=lambda v: json.dumps(v).encode(),
                                 key_serializer=lambda k: str(k).encode())
        except KafkaError:
            print(f"[producer] Kafka not ready ({attempt + 1}/{retries}), retrying in 2s")
            time.sleep(2)
    raise SystemExit("[producer] could not connect to Kafka")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["baseline", "drift"], default=os.environ.get("PRODUCER_MODE", "baseline"))
    parser.add_argument("--rate", type=float, default=float(os.environ.get("PRODUCER_RATE", 5)),
                        help="messages per second")
    parser.add_argument("--limit", type=int, default=int(os.environ.get("PRODUCER_LIMIT", 0)),
                        help="stop after N messages (0 = loop forever)")
    args = parser.parse_args(argv)

    comments = load_comments(args.mode, Path(os.environ.get("DATA_DIR", "data/processed")))
    producer = connect(os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092"))
    print(f"[producer] streaming {len(comments)} {args.mode} comments at {args.rate}/s to {TOPIC}")

    sent = 0
    while True:
        for row in comments.itertuples(index=False):
            msg = {"id": f"{args.mode}-{row.id}-{sent}", "text": row.comment_text,
                   "source": args.mode, "ts": datetime.now(UTC).isoformat()}
            producer.send(TOPIC, key=msg["id"], value=msg)
            sent += 1
            if sent % 100 == 0:
                print(f"[producer] sent {sent}")
            if args.limit and sent >= args.limit:
                producer.flush()
                return
            time.sleep(1.0 / args.rate)


if __name__ == "__main__":
    main()
