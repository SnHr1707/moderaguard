from moderaguard.responsible.quality_gate import evaluate_gate

CFG = {"min_auc": 0.8, "max_auc_drop": 0.005, "max_fairness_gap_increase": 0.02}


def test_better_and_fairer_model_passes():
    r = evaluate_gate({"auc": 0.95}, {"auc": 0.94}, {"worst_fpr_gap": 0.05}, {"worst_fpr_gap": 0.06}, CFG)
    assert r["passed"]


def test_more_accurate_but_less_fair_model_fails():
    r = evaluate_gate({"auc": 0.97}, {"auc": 0.94}, {"worst_fpr_gap": 0.15}, {"worst_fpr_gap": 0.05}, CFG)
    assert not r["passed"]
    assert [c["check"] for c in r["checks"] if not c["passed"]] == ["fairness_gap_vs_champion"]


def test_worse_auc_fails():
    r = evaluate_gate({"auc": 0.90}, {"auc": 0.94}, None, None, CFG)
    assert not r["passed"]


def test_first_model_only_needs_min_auc():
    assert evaluate_gate({"auc": 0.85}, None, None, None, CFG)["passed"]
    assert not evaluate_gate({"auc": 0.70}, None, None, None, CFG)["passed"]
