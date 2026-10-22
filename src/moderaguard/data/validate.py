"""Data validation with Pandera (owner: M1).

Every pipeline stage that reads data validates it first, so a bad file stops
the pipeline with a clear message instead of silently training a bad model.

Run:  python -m moderaguard.data.validate
"""

from __future__ import annotations

import json
import sys

import pandas as pd
import pandera.pandas as pa
from pandera.errors import SchemaErrors

from moderaguard.config import PROCESSED_DIR, REPORTS_DIR, ensure_dirs, params


def toxicity_schema() -> pa.DataFrameSchema:
    identity_cols = params()["fairness"]["identity_columns"]
    return pa.DataFrameSchema(
        {
            "id": pa.Column(int, unique=True),
            "comment_text": pa.Column(
                str,
                checks=[pa.Check.str_length(min_value=1, max_value=5000)],
                nullable=False,
            ),
            "toxic": pa.Column(int, checks=pa.Check.isin([0, 1])),
            "created_date": pa.Column("datetime64[ns, UTC]"),
            **{
                col: pa.Column(float, checks=pa.Check.in_range(0.0, 1.0), nullable=True)
                for col in identity_cols
            },
        },
        checks=[
            # a usable training set has both classes in a sensible ratio
            pa.Check(lambda df: 0.01 <= df["toxic"].mean() <= 0.9, error="toxic share out of range"),
            pa.Check(lambda df: len(df) >= 100, error="fewer than 100 rows"),
        ],
        strict=False,
        coerce=True,
    )


def spam_schema() -> pa.DataFrameSchema:
    return pa.DataFrameSchema(
        {
            "id": pa.Column(str, unique=True),
            "text": pa.Column(str, checks=pa.Check.str_length(min_value=1, max_value=5000)),
            "spam": pa.Column(int, checks=pa.Check.isin([0, 1])),
        },
        checks=[pa.Check(lambda df: 0.05 <= df["spam"].mean() <= 0.95, error="spam share out of range")],
        strict=True,
        coerce=True,
    )


def validate_frame(df: pd.DataFrame, schema: pa.DataFrameSchema, name: str) -> pd.DataFrame:
    try:
        return schema.validate(df, lazy=True)
    except SchemaErrors as err:
        cases = err.failure_cases.head(20).to_dict(orient="records")
        raise ValueError(f"{name}: {len(err.failure_cases)} validation failures, e.g. {cases}") from err


def main() -> None:
    ensure_dirs()
    results = {}
    ok = True
    for name, schema in (("toxicity", toxicity_schema()), ("spam", spam_schema())):
        for split in ("train", "test"):
            path = PROCESSED_DIR / f"{name}_{split}.parquet"
            df = pd.read_parquet(path)
            try:
                validate_frame(df, schema, f"{name}_{split}")
                results[f"{name}_{split}"] = {"rows": len(df), "status": "passed"}
            except ValueError as e:
                ok = False
                results[f"{name}_{split}"] = {"rows": len(df), "status": "failed", "error": str(e)[:2000]}
    (REPORTS_DIR / "validation.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
