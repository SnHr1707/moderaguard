"""Generate a small synthetic sample in the same format as the real datasets.

The sample lets everyone run the whole pipeline, the tests and the Docker
stack before the real data is downloaded. It mimics:

* Jigsaw "all_data.csv": id, comment_text, toxicity, created_date, identity columns
* UCI YouTube Spam Collection: COMMENT_ID, AUTHOR, DATE, CONTENT, CLASS

Two properties are built in on purpose so the MLOps parts have something real
to show:

* Drift: comments after the drift split date use newer slang, so the drift job
  detects a shift when the producer streams them.
* Bias: neutral comments that mention some identity groups are mislabelled as
  toxic slightly more often (as happens with real annotators), so the fairness
  audit finds a gap that mitigation can reduce.

Run:  python -m moderaguard.data.make_sample
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from moderaguard.config import SAMPLE_DIR

IDENTITY_TERMS = {
    "male": ["men", "guys", "he"],
    "female": ["women", "girls", "she"],
    "homosexual_gay_or_lesbian": ["gay people", "lesbians"],
    "christian": ["christians", "the church"],
    "jewish": ["jewish people", "jews"],
    "muslim": ["muslims", "islam"],
    "black": ["black people"],
    "white": ["white people"],
    "psychiatric_or_mental_illness": ["people with depression", "the mentally ill"],
}
# Groups whose neutral mentions get extra false "toxic" labels (simulated annotator bias)
BIASED_GROUPS = {"homosexual_gay_or_lesbian", "muslim", "black"}

NEUTRAL = [
    "I think {who} made a fair point in this article",
    "Thanks for sharing, this was a helpful read about {who}",
    "The city council should publish the budget before the vote",
    "Interesting analysis, though I would like to see more data",
    "My neighbour said {who} organised the community clean-up",
    "This policy will affect {who} and everyone else in the region",
    "Great reporting, please keep covering local news",
    "I disagree with the author but respect the argument",
    "Does anyone know when the new bridge opens",
    "Good to see {who} represented in the discussion",
]
TOXIC_OLD = [
    "You are a complete idiot and should shut up",
    "What a stupid pathetic comment from {who}",
    "Only a moron would write garbage like this",
    "Get lost you worthless loser",
    "{who} are disgusting and should be ashamed",
    "This author is a clown and an absolute fool",
]
# Newer slang that appears only after the drift date. It deliberately shares no
# insult words with TOXIC_OLD, so a model trained before the drift date misses
# it and retraining has something real to learn.
TOXIC_NEW = [
    "Ratio plus you are cringe and nobody asked",
    "Absolute L take, touch grass you npc",
    "Mid opinion from a bot, stay pressed",
    "{who} posting this is peak cringe, go touch grass",
    "Imagine being this much of an npc, ratio",
    "Cope and seethe, this is so cringe",
]
NEUTRAL_NEW = [
    "Lowkey this is a solid take on the housing issue",
    "Ngl the new transit plan seems reasonable",
    "This thread actually has some good points fr",
    "{who} had a valid point in that interview tbh",
]
NON_ENGLISH = [
    "Muy buen articulo, gracias por compartir",
    "Je ne suis pas d'accord avec cet article",
    "Das ist ein sehr interessanter Beitrag",
    "Yeh article bahut accha hai, dhanyavaad",
]
SPAM = [
    "Check out my channel for free giveaways http://bit.ly/{n}",
    "Subscribe to me and I will subscribe back!!!",
    "Make money fast working from home, visit www.cashnow{n}.com",
    "Please like and subscribe to my new music video",
    "FREE gift cards here >>> http://tinyurl.com/{n}",
    "I just reached 1000 subs, check my page please",
]
HAM = [
    "This song brings back so many memories",
    "The guitar solo at 2:30 is amazing",
    "Who is still listening to this in 2015?",
    "The video quality is great, love the colours",
    "My favourite track from the whole album",
    "The dance in this video is so fun to watch",
]


def _pick(rng: np.random.Generator, options: list[str]) -> str:
    return options[rng.integers(len(options))]


def make_toxicity(n: int, rng: np.random.Generator, drift_date: datetime) -> pd.DataFrame:
    start = datetime(2015, 9, 1)
    span_days = (datetime(2017, 11, 1) - start).days
    rows = []
    for i in range(n):
        created = start + timedelta(days=int(rng.integers(span_days)), seconds=int(rng.integers(86400)))
        after_drift = created >= drift_date
        identity = {col: 0.0 for col in IDENTITY_TERMS}
        group = None
        if rng.random() < 0.03:
            text, score = _pick(rng, NON_ENGLISH), 0.0
        else:
            toxic = rng.random() < 0.25
            if toxic:
                pool = TOXIC_NEW if after_drift and rng.random() < 0.7 else TOXIC_OLD
            else:
                pool = NEUTRAL_NEW if after_drift and rng.random() < 0.5 else NEUTRAL
            template = _pick(rng, pool)
            # a group is "mentioned" only if the sentence actually names it
            if "{who}" in template and rng.random() < 0.6:
                group = list(IDENTITY_TERMS)[rng.integers(len(IDENTITY_TERMS))]
                identity[group] = 1.0
            who = _pick(rng, IDENTITY_TERMS[group]) if group else "people"
            text = template.format(who=who)
            score = float(rng.uniform(0.55, 1.0)) if toxic else float(rng.uniform(0.0, 0.3))
            # simulated annotator bias: some neutral comments that name certain groups
            # were labelled toxic by annotators
            if not toxic and group in BIASED_GROUPS and rng.random() < 0.25:
                score = float(rng.uniform(0.5, 0.7))
        rows.append(
            {
                "id": 100000 + i,
                "comment_text": text,
                "toxicity": round(score, 4),
                "created_date": created.strftime("%Y-%m-%d %H:%M:%S.%f+00"),
                **identity,
            }
        )
    return pd.DataFrame(rows)


def make_spam(n: int, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for i in range(n):
        spam = rng.random() < 0.5
        text = _pick(rng, SPAM if spam else HAM).format(n=rng.integers(1000, 9999))
        rows.append(
            {
                "COMMENT_ID": f"sample{i:05d}",
                "AUTHOR": f"user{rng.integers(10000)}",
                "DATE": f"2015-0{rng.integers(1, 9)}-1{rng.integers(0, 9)}T10:00:00",
                "CONTENT": text,
                "CLASS": int(spam),
            }
        )
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toxicity-rows", type=int, default=8000)
    parser.add_argument("--spam-rows", type=int, default=1200)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)

    rng = np.random.default_rng(args.seed)
    (SAMPLE_DIR / "jigsaw").mkdir(parents=True, exist_ok=True)
    (SAMPLE_DIR / "youtube_spam").mkdir(parents=True, exist_ok=True)

    tox = make_toxicity(args.toxicity_rows, rng, datetime(2017, 6, 1))
    tox.to_csv(SAMPLE_DIR / "jigsaw" / "all_data.csv", index=False)
    spam = make_spam(args.spam_rows, rng)
    spam.to_csv(SAMPLE_DIR / "youtube_spam" / "Youtube_sample.csv", index=False)
    print(f"wrote {len(tox)} toxicity rows and {len(spam)} spam rows to {SAMPLE_DIR}")


if __name__ == "__main__":
    main()
