import pandas as pd

from moderaguard.responsible.fairness import bias_metrics, final_bias_score


def _frame():
    # 40 comments about group "g", 40 background; the model over-scores neutral "g" comments
    rows = []
    for i in range(40):
        rows.append({"g": 1.0, "toxic": int(i < 10), "score": 0.9 if i < 10 else 0.85})
        rows.append({"g": 0.0, "toxic": int(i < 10), "score": 0.8 if i < 10 else 0.1})
    return pd.DataFrame(rows)


def test_bpsn_auc_detects_false_positives_on_group():
    table = bias_metrics(_frame(), ["g"], threshold=0.5, min_size=10)
    row = table.iloc[0]
    assert row.subgroup_auc == 1.0          # within the group the model still ranks correctly
    assert row.bpsn_auc < row.bnsp_auc      # but neutral group comments outrank toxic background ones


def test_small_groups_are_skipped():
    assert bias_metrics(_frame(), ["g"], threshold=0.5, min_size=100).empty


def test_final_score_is_between_zero_and_one():
    table = bias_metrics(_frame(), ["g"], threshold=0.5, min_size=10)
    assert 0 < final_bias_score(0.9, table) <= 1
