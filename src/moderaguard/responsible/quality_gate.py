"""Quality gate: decides whether a candidate model may be deployed (owner: M4, used by M6's Jenkins).

A candidate passes only if:
  1. its test AUC is at least `min_auc`,
  2. its AUC is not more than `max_auc_drop` below the current champion, and
  3. for toxicity, its worst false-positive-rate gap across identity groups
     is not more than `max_fairness_gap_increase` above the champion's.

So a model that is more accurate but less fair is rejected.

Exit code 0 = pass, 1 = fail. Writes reports/gate_<task>.json.

Run:  python -m moderaguard.responsible.quality_gate --task toxicity --candidate challenger --baseline champion
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from moderaguard.config import REPORTS_DIR, ensure_dirs, params


def _load(path: Path) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


def evaluate_gate(candidate_metrics: dict, baseline_metrics: dict | None,
                  candidate_fair: dict | None, baseline_fair: dict | None, cfg: dict) -> dict:
    checks = []
    auc = candidate_metrics["auc"]
    checks.append({"check": "min_auc", "passed": auc >= cfg["min_auc"],
                   "detail": f"candidate AUC {auc} vs minimum {cfg['min_auc']}"})
    if baseline_metrics is not None:
        drop = round(baseline_metrics["auc"] - auc, 4)
        checks.append({"check": "auc_vs_champion", "passed": drop <= cfg["max_auc_drop"],
                       "detail": f"AUC drop {drop} vs allowed {cfg['max_auc_drop']}"})
    if candidate_fair is not None and baseline_fair is not None:
        increase = round(candidate_fair["worst_fpr_gap"] - baseline_fair["worst_fpr_gap"], 4)
        checks.append({"check": "fairness_gap_vs_champion", "passed": increase <= cfg["max_fairness_gap_increase"],
                       "detail": f"worst FPR gap change {increase:+} vs allowed +{cfg['max_fairness_gap_increase']}"})
    return {"passed": all(c["passed"] for c in checks), "checks": checks}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--task", choices=["toxicity", "spam"], default="toxicity")
    parser.add_argument("--candidate", default="challenger")
    parser.add_argument("--baseline", default="champion")
    args = parser.parse_args(argv)
    ensure_dirs()

    cand = _load(REPORTS_DIR / f"metrics_{args.task}_{args.candidate}.json")
    if cand is None:
        print(f"[gate] no metrics for candidate '{args.candidate}'. Train it first.")
        return 1
    base = None if args.candidate == args.baseline else _load(REPORTS_DIR / f"metrics_{args.task}_{args.baseline}.json")
    cand_fair = _load(REPORTS_DIR / f"fairness_{args.candidate}.json") if args.task == "toxicity" else None
    base_fair = _load(REPORTS_DIR / f"fairness_{args.baseline}.json") if args.task == "toxicity" and base else None

    result = evaluate_gate(cand, base, cand_fair, base_fair, params()["quality_gate"])
    result.update({"task": args.task, "candidate": args.candidate, "baseline": args.baseline})
    (REPORTS_DIR / f"gate_{args.task}.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
