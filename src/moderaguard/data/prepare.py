"""Ingest raw data and produce the processed splits (owner: M1).

Outputs in data/processed/:
  toxicity_train.parquet   comments before the drift date (80%)
  toxicity_test.parquet    comments before the drift date (20%)
  toxicity_stream.parquet  comments on/after the drift date, replayed by the producer
  spam_train.parquet / spam_test.parquet

If the real datasets are not in data/raw/, the sample in data/sample/ is used,
so the pipeline always runs.

With --include-stream (used by the retraining DAG), the newer comments that
have since been labelled are added to the train/test splits, so the retrained
model learns the new vocabulary. In production these labels would come from
moderator feedback; here the Jigsaw labels play that role.

Run:  python -m moderaguard.data.prepare [--include-stream]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split

from moderaguard.config import PROCESSED_DIR, REPORTS_DIR, ROOT, SAMPLE_DIR, ensure_dirs, params


def _resolve(path: Path, sample: Path) -> tuple[Path, bool]:
    if path.exists():
        return path, False
    print(f"[prepare] {path} not found, using sample data {sample}")
    return sample, True


def load_toxicity(p: dict) -> tuple[pd.DataFrame, bool]:
    path, is_sample = _resolve(ROOT / p["data"]["jigsaw_path"], SAMPLE_DIR / "jigsaw" / "all_data.csv")
    identity_cols = p["fairness"]["identity_columns"]
    usecols = ["id", "comment_text", "toxicity", "created_date", *identity_cols]
    df = pd.read_csv(path, usecols=usecols)
    df = df.dropna(subset=["comment_text", "toxicity", "created_date"])
    df["comment_text"] = df["comment_text"].astype(str).str.strip()
    df = df[df["comment_text"].str.len() > 0]
    df["created_date"] = pd.to_datetime(df["created_date"], utc=True, format="mixed")
    df["toxic"] = (df["toxicity"] >= p["data"]["toxicity_threshold"]).astype(int)
    if len(df) > p["data"]["max_rows"]:
        df = df.sample(p["data"]["max_rows"], random_state=p["data"]["seed"])
    return df.drop(columns=["toxicity"]).reset_index(drop=True), is_sample


def load_spam(p: dict) -> tuple[pd.DataFrame, bool]:
    spam_dir = ROOT / p["data"]["spam_dir"]
    files = sorted(spam_dir.glob("*.csv")) if spam_dir.exists() else []
    is_sample = not files
    if is_sample:
        print(f"[prepare] no CSVs in {spam_dir}, using sample data")
        files = sorted((SAMPLE_DIR / "youtube_spam").glob("*.csv"))
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    df = df.rename(columns={"COMMENT_ID": "id", "CONTENT": "text", "CLASS": "spam"})[["id", "text", "spam"]]
    df = df.dropna().drop_duplicates(subset="id")
    df["id"] = df["id"].astype(str)
    df["spam"] = df["spam"].astype(int)
    return df.reset_index(drop=True), is_sample


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--include-stream", action="store_true",
                        help="add the labelled newer comments to training (retraining after drift)")
    args = parser.parse_args(argv)
    ensure_dirs()
    p = params()
    seed, test_size = p["data"]["seed"], p["data"]["test_size"]

    tox, tox_sample = load_toxicity(p)
    split_date = pd.Timestamp(p["data"]["drift_split_date"], tz="UTC")
    before, after = tox[tox["created_date"] < split_date], tox[tox["created_date"] >= split_date]
    tox_train, tox_test = train_test_split(before, test_size=test_size, random_state=seed, stratify=before["toxic"])
    stream = after.sort_values("created_date")
    if args.include_stream:
        # The older split stays exactly as it was, so no comment the current champion
        # trained on can leak into the test set; the newer comments are split on
        # their own and added to both sides.
        new_train, new_test = train_test_split(after, test_size=test_size, random_state=seed,
                                               stratify=after["toxic"])
        tox_train = pd.concat([tox_train, new_train], ignore_index=True)
        tox_test = pd.concat([tox_test, new_test], ignore_index=True)

    spam, spam_sample = load_spam(p)
    spam_train, spam_test = train_test_split(spam, test_size=test_size, random_state=seed, stratify=spam["spam"])

    outputs = {
        "toxicity_train": tox_train,
        "toxicity_test": tox_test,
        "toxicity_stream": stream,
        "spam_train": spam_train,
        "spam_test": spam_test,
    }
    for name, frame in outputs.items():
        frame.to_parquet(PROCESSED_DIR / f"{name}.parquet", index=False)

    summary = {
        "source": {"toxicity": "sample" if tox_sample else "jigsaw", "spam": "sample" if spam_sample else "uci"},
        "include_stream": args.include_stream,
        "rows": {k: len(v) for k, v in outputs.items()},
        "toxic_share_train": round(float(tox_train["toxic"].mean()), 4),
        "spam_share_train": round(float(spam_train["spam"].mean()), 4),
    }
    (REPORTS_DIR / "data_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
