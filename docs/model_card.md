# Model card: ModeraGuard toxicity model (owner: M4)

Following *Model Cards for Model Reporting* (Mitchell et al., 2019). Numbers
are from the synthetic sample data; update them after training on Jigsaw.

## Model details

| | |
| --- | --- |
| Registered name | `moderaguard-toxicity` (MLflow), aliases `champion` and `challenger` |
| Champion | TF-IDF word 1–2-grams + character 3–5-grams → logistic regression (C = 4, balanced class weights) |
| Challenger | Same features → linear SVM (C = 0.5) with probability calibration |
| Bias mitigation | Identity-term masking (every identity word becomes the token `identityterm`, in training and serving) + 3× weight for harmless comments that mention a group |
| Inputs | One English comment, up to 5,000 characters |
| Output | Probability that the comment is toxic, in [0, 1] |
| Training code | `src/moderaguard/models/train.py`; settings in `params.yaml` |
| Owners | M3 (training), M4 (evaluation and governance) |

Companion models: `moderaguard-spam` (same features, logistic regression, YouTube
Spam Collection) and `moderaguard-langid` (fastText `lid.176` or a stop-word
fallback).

## Intended use

- **Primary use:** triage of user comments on a news or discussion site. The
  model's score feeds the gateway, which **allows**, **sends to human review** or
  **blocks**. Blocking needs a score of at least 0.85; scores from 0.5 to 0.85
  go to a human moderator.
- **Users:** moderation teams who can see why a comment was flagged (`/explain`)
  and overrule it (`/feedback`).
- **Out of scope:** fully automatic removal without appeal; judging people
  rather than comments; languages other than English (the gateway sends those
  to human review instead of scoring them); legal decisions.

## Training and evaluation data

- Jigsaw Unintended Bias in Toxicity Classification (Civil Comments, 2015–2017),
  subsampled to 200,000 comments; a comment is "toxic" when at least half the
  annotators said so.
- Split by time: comments before 2017-06-01 for training and testing (80/20,
  stratified); later comments are held back as a stream that reproduces real
  drift. After drift, the retraining DAG adds a labelled share of the newer
  comments without moving any older comment into the test set.

## Metrics

| Metric | Why |
| --- | --- |
| ROC AUC | Threshold-free ranking quality; the quality gate's main accuracy check |
| Precision, recall, F1 at 0.5 | What moderators experience at the serving threshold |
| Subgroup, BPSN, BNSP AUC per identity group | Jigsaw's unintended-bias metrics: does the model rank comments about a group worse? |
| False-positive rate per group (Fairlearn `MetricFrame`) | How often harmless comments about a group are flagged |
| Final bias score | Jigsaw's combined metric (overall AUC + power means of the bias AUCs) |

## Results (synthetic sample)

| Model | AUC | F1 | Worst FPR gap | Final bias score |
| --- | --- | --- | --- | --- |
| Without mitigation | 0.998 | 0.933 | 0.68 | 0.961 |
| Champion (mitigated) | 0.993 | 0.967 | 0.00 | 0.961 |
| Challenger (mitigated) | 0.993 | 0.967 | 0.00 | 0.961 |

On the synthetic sample both mitigated models rank the test comments almost identically; the
only errors left are the deliberately mislabelled comments. Expect them to differ on real data.

Per-group numbers: [fairness_report.md](fairness_report.md).

## Ethical considerations

- **Identity terms.** Annotators label harmless comments that mention some
  groups as toxic more often, and an unmitigated model learns that bias:
  without mitigation the score of *"Good to see {group} represented in the
  discussion"* ranges from 0.01 to 0.56 depending on the group. Mitigation
  narrows that range to 0.00 at a cost of 0.005 AUC. Counterfactual
  augmentation was tried first and made the gap worse (it copied the biased
  labels to every group), so it is off by default. The quality gate rejects
  any new model that widens the worst false-positive gap by more than 0.02,
  even if it is more accurate.
- **Dialect and reclaimed language.** Word-based models over-flag some dialects
  and reclaimed slurs. The audit only covers the nine annotated identity groups;
  this is a known gap.
- **Privacy.** E-mails, URLs, phone numbers and handles are masked before any
  comment text is logged or stored (`responsible/redact.py`). Models still see
  the original text.
- **Human oversight.** Uncertain scores go to people; every decision can be
  explained and overruled, and overrules are logged as future training labels.

## Caveats and recommendations

- Retrain when the drift alert fires or moderator disagreement exceeds 30%
  (Prometheus alerts `ModelDriftDetected`, `ModeratorDisagreementHigh`).
- Recalibrate thresholds after every retrain; scores are not comparable across
  model versions.
- The sample-data numbers are optimistic (the sample is small and templated);
  only numbers from the real data should be quoted outside this course.
