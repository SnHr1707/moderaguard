"""ModeraGuard moderator console (owner: M4).

The demo's home page. Six tabs:
  Moderate     check a comment: verdict, scores, the words that drove the decision, feedback
  Live stream  comments flowing through Kafka, read from the prediction log (refreshes itself)
  Review queue the comments the gateway was unsure about, for a moderator to allow or block
  Models       registered model versions and their metrics from MLflow, plus evaluation charts
  Fairness     false-positive rate per identity group, before and after bias mitigation
  System       which services are up, and what to look at in each tool

Every data source is optional: a tab that cannot reach its source says so
instead of failing, so the console works even while the stack is starting.

Env: GATEWAY_URL, MLFLOW_URL, PREDICTIONS_DSN, MODELS_DIR, REPORTS_DIR, and the
public *_PUBLIC_URL links shown to the user (defaults: localhost ports).
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path

import altair as alt
import httpx
import pandas as pd
import streamlit as st

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://gateway:8000")
MLFLOW_URL = os.environ.get("MLFLOW_URL", "http://mlflow:5000")
PREDICTIONS_DSN = os.environ.get("PREDICTIONS_DSN", "")
# The gateway's review thresholds (services/gateway/gateway.py), used to explain a review
TOX_REVIEW, SPAM_REVIEW = 0.5, 0.6
MODELS_DIR = Path(os.environ.get("MODELS_DIR", "/data/models"))
REPORTS_DIR = Path(os.environ.get("REPORTS_DIR", "/data/reports"))
DISPLAY_TZ = os.environ.get("DISPLAY_TZ", "Asia/Kolkata")

# (name, internal health URL, public URL, what to show the professor there)
TOOLS = [
    ("Gateway API", f"{GATEWAY_URL}/health", os.environ.get("GATEWAY_PUBLIC_URL", "http://localhost:8000/docs"),
     "Swagger page: try /moderate and /explain live."),
    ("MLflow", f"{MLFLOW_URL}/health", os.environ.get("MLFLOW_PUBLIC_URL", "http://localhost:5000"),
     "Experiments → moderaguard-toxicity: runs, metrics, charts. Models: champion / challenger aliases."),
    ("Airflow", os.environ.get("AIRFLOW_HEALTH_URL", "http://airflow:8080/api/v2/monitor/health"),
     os.environ.get("AIRFLOW_PUBLIC_URL", "http://localhost:8080"),
     "DAGs → retrain_dag → Graph: the retraining pipeline and its quality gate."),
    ("Grafana", os.environ.get("GRAFANA_HEALTH_URL", "http://grafana:3000/api/health"),
     os.environ.get("GRAFANA_PUBLIC_URL", "http://localhost:3000"),
     "Dashboards → ModeraGuard: traffic, verdicts, drift score, server and database."),
    ("Prometheus", os.environ.get("PROMETHEUS_HEALTH_URL", "http://prometheus:9090/-/ready"),
     os.environ.get("PROMETHEUS_PUBLIC_URL", "http://localhost:9090"),
     "Status → Target health (all UP); Alerts: the rules and which are firing."),
    ("Alertmanager", os.environ.get("ALERTMANAGER_HEALTH_URL", "http://alertmanager:9093/-/ready"),
     os.environ.get("ALERTMANAGER_PUBLIC_URL", "http://localhost:9093"),
     "Shows ModelDriftDetected while drift is happening (empty otherwise)."),
]

VERDICT = {
    "allow": ("Allowed", "#15803d", "#dcfce7"),
    "review": ("Sent to human review", "#b45309", "#fef3c7"),
    "block": ("Blocked", "#b91c1c", "#fee2e2"),
}
REASONS = {
    "toxic": "toxicity above the block threshold (0.85)",
    "possibly_toxic": "toxicity above the review threshold (0.5)",
    "spam": "spam above the block threshold (0.9)",
    "possibly_spam": "spam above the review threshold (0.6)",
}
EXAMPLES = {
    "Friendly": "Thanks for sharing, this was a really helpful read",
    "Insult": "What a stupid pathetic comment from the author",
    "Spam": "Subscribe to my channel for free gift cards http://bit.ly/9999",
    "New slang": "Absolute L take, touch grass you npc",
    "Identity, harmless": "Good to see gay people represented in the discussion",
    "Spanish": "Muy buen articulo, gracias por compartir",
    "Contains e-mail": "Email me at priya@example.com, the author is a moron",
}

st.set_page_config(page_title="ModeraGuard", page_icon="🛡️", layout="wide")
st.markdown("""
<style>
.block-container {padding-top: 1.6rem; max-width: 1200px;}
.mg-verdict {border-radius: 10px; padding: 14px 18px; margin: 4px 0 12px 0;}
.mg-verdict h3 {margin: 0; font-size: 1.35rem;}
.mg-verdict p {margin: 4px 0 0 0;}
.mg-words {line-height: 2.1; font-size: 1.05rem;}
.mg-words span {padding: 2px 4px; border-radius: 4px;}
.mg-muted {color: #6b7280; font-size: 0.9rem;}
</style>
""", unsafe_allow_html=True)


# ----------------------------------------------------------------- helpers
@st.cache_resource
def http() -> httpx.Client:
    return httpx.Client(timeout=8)


def gateway(path: str, payload: dict) -> dict | None:
    try:
        r = http().post(f"{GATEWAY_URL}{path}", json=payload)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        st.error(f"The gateway is not reachable ({e.__class__.__name__}). Is the stack running?")
        return None


@st.cache_data(ttl=15)
def tool_status() -> dict[str, bool]:
    out = {}
    for name, health, _, _ in TOOLS:
        try:
            out[name] = http().get(health).status_code < 500
        except httpx.HTTPError:
            out[name] = False
    return out


def highlight(text: str, contributions: list[dict]) -> str:
    """Colour each word by how much it raised the toxicity score."""
    weight = {}
    for c in contributions:
        weight[c["word"]] = max(weight.get(c["word"], 0.0), c["contribution"])
    top = max([w for w in weight.values() if w > 0], default=1.0)
    parts = []
    for word in text.split():
        w = weight.get(word, 0.0)
        alpha = 0.0 if w <= 0 else 0.15 + 0.7 * (w / top)
        style = f"background: rgba(220,38,38,{alpha:.2f});" if alpha else ""
        parts.append(f'<span style="{style}" title="+{w:.3f}">{html.escape(word)}</span>')
    return '<div class="mg-words">' + " ".join(parts) + "</div>"


def score_bar(label: str, value: float | None, review: float, block: float) -> None:
    if value is None:
        st.metric(label, "not scored")
        st.caption("Only English comments are scored.")
        return
    st.metric(label, f"{value:.2f}")
    st.progress(min(max(value, 0.0), 1.0))
    st.caption(f"review ≥ {review} · block ≥ {block}")


@st.cache_data(ttl=10)
def recent_predictions(limit: int = 500) -> pd.DataFrame | None:
    if not PREDICTIONS_DSN:
        return None
    try:
        import psycopg2

        with psycopg2.connect(PREDICTIONS_DSN, connect_timeout=3) as conn, conn.cursor() as cur:
            cur.execute("SELECT id, text, source, language, toxicity, spam, verdict, toxicity_model, ts "
                        "FROM predictions ORDER BY ts DESC LIMIT %s", (limit,))
            cols = [d[0] for d in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=cols)
    except Exception:  # noqa: BLE001 - table not created yet, DB starting, ...
        return None


def review_queue(limit: int = 15) -> tuple[pd.DataFrame | None, int, int]:
    """Comments the gateway sent to review that no moderator has decided yet.

    Returns (oldest waiting comments, number waiting, number decided)."""
    if not PREDICTIONS_DSN:
        return None, 0, 0
    try:
        import psycopg2

        with psycopg2.connect(PREDICTIONS_DSN, connect_timeout=3) as conn, conn.cursor() as cur:
            # the gateway creates the feedback table on the first decision; make sure it exists
            cur.execute("""CREATE TABLE IF NOT EXISTS feedback (id TEXT, text TEXT, predicted_verdict TEXT,
                           correct_verdict TEXT, moderator TEXT, ts TIMESTAMPTZ)""")
            pending = "FROM predictions p WHERE p.verdict = 'review' AND NOT EXISTS " \
                      "(SELECT 1 FROM feedback f WHERE f.id = p.id)"
            cur.execute(f"SELECT count(*) {pending}")
            waiting = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM feedback WHERE predicted_verdict = 'review'")
            decided = cur.fetchone()[0]
            cur.execute(f"SELECT id, text, language, toxicity, spam, ts {pending} ORDER BY ts LIMIT %s", (limit,))
            cols = [d[0] for d in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=cols), waiting, decided
    except Exception:  # noqa: BLE001 - table not created yet, DB starting, ...
        return None, 0, 0


def review_reason(row) -> str:
    if row.language != "en":
        return f"not English ({row.language}): the models only read English"
    reasons = []
    if row.toxicity is not None and row.toxicity >= TOX_REVIEW:
        reasons.append(f"maybe toxic ({row.toxicity:.2f})")
    if row.spam is not None and row.spam >= SPAM_REVIEW:
        reasons.append(f"maybe spam ({row.spam:.2f})")
    return ", ".join(reasons) or "borderline score"


@st.cache_data(ttl=30)
def mlflow_models() -> list[dict] | None:
    try:
        r = http().get(f"{MLFLOW_URL}/api/2.0/mlflow/registered-models/search", params={"max_results": 50})
        r.raise_for_status()
        models = []
        for rm in r.json().get("registered_models", []):
            versions = http().get(f"{MLFLOW_URL}/api/2.0/mlflow/model-versions/search",
                                  params={"filter": f"name='{rm['name']}'", "max_results": 50}).json()
            aliases = {}
            for a in rm.get("aliases", []):
                aliases.setdefault(a["version"], []).append(a["alias"])
            for v in versions.get("model_versions", []):
                metrics = {}
                if v.get("run_id"):
                    run = http().get(f"{MLFLOW_URL}/api/2.0/mlflow/runs/get", params={"run_id": v["run_id"]}).json()
                    metrics = {m["key"]: m["value"] for m in run.get("run", {}).get("data", {}).get("metrics", [])}
                models.append({
                    "model": rm["name"].replace("moderaguard-", ""),
                    "version": int(v["version"]),
                    "aliases": ", ".join(aliases.get(v["version"], [])),
                    "AUC": metrics.get("auc"), "F1": metrics.get("f1"),
                    "precision": metrics.get("precision"), "recall": metrics.get("recall"),
                    "worst FPR gap": metrics.get("fairness.worst_fpr_gap"),
                    "trained": pd.to_datetime(int(v["creation_timestamp"]), unit="ms", utc=True)
                    .tz_convert(DISPLAY_TZ).tz_localize(None),
                })
        return sorted(models, key=lambda m: (m["model"], -m["version"]))
    except (httpx.HTTPError, ValueError, KeyError):
        return None


def load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


# ----------------------------------------------------------------- header
st.title("🛡️ ModeraGuard")
st.markdown("Multi-model comment moderation with fairness auditing and drift-triggered retraining")
status = tool_status()
st.caption(f"**{sum(status.values())} of {len(status)} tools reachable** · "
           + " · ".join(f"{'🟢' if ok else '🔴'} {name}" for name, ok in status.items()))

tab_mod, tab_live, tab_review, tab_models, tab_fair, tab_sys = st.tabs(
    ["Moderate", "Live stream", "Review queue", "Models", "Fairness", "System"])

# ----------------------------------------------------------------- Moderate
with tab_mod:
    st.markdown("Type a comment or pick an example. The gateway detects the language, scores toxicity "
                "and spam in parallel, and decides **allow**, **review** or **block**.")
    picked = st.pills("Examples", list(EXAMPLES), selection_mode="single", key="example")
    if picked and st.session_state.get("last_example") != picked:
        st.session_state["comment"] = EXAMPLES[picked]
        st.session_state["last_example"] = picked
    text = st.text_area("Comment", key="comment", height=100, placeholder="Paste a comment to moderate")

    if st.button("Moderate", type="primary", disabled=not (text or "").strip()):
        result = gateway("/moderate", {"text": text})
        if result:
            st.session_state["result"] = result
            st.session_state["result_text"] = text
            st.session_state["explanation"] = (gateway("/explain", {"text": text})
                                               if result.get("toxicity") is not None else None)

    result = st.session_state.get("result")
    if result and "verdict" in result:
        label, fg, bg = VERDICT[result["verdict"]]
        reasons = [REASONS.get(r, r.replace("unsupported_language:", "language '") + ("'" if ":" in r else ""))
                   for r in result["reasons"]]
        if any(r.startswith("unsupported_language") for r in result["reasons"]):
            reasons = [f"the models are English-only, so a person checks this {result['language']} comment"]
        st.markdown(
            f'<div class="mg-verdict" style="background:{bg}; border-left: 6px solid {fg};">'
            f'<h3 style="color:{fg}">{label}</h3>'
            f'<p>{html.escape("; ".join(reasons) if reasons else "no score crossed a threshold")}</p></div>',
            unsafe_allow_html=True)

        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Language", result["language"], f"{result['language_confidence']:.0%} confidence",
                      delta_color="off")
        with c2:
            score_bar("Toxicity", result["toxicity"], 0.5, 0.85)
        with c3:
            score_bar("Spam", result["spam"], 0.6, 0.9)

        explanation = st.session_state.get("explanation")
        if explanation and explanation.get("contributions"):
            st.subheader("Why: the words that pushed the toxicity score up")
            st.markdown(highlight(st.session_state["result_text"], explanation["contributions"]),
                        unsafe_allow_html=True)
            st.caption("Each word is removed in turn and the comment re-scored; darker red means the "
                       "toxicity (in log-odds) dropped more without that word. Hover a word for the number.")

        with st.expander("Model versions and raw response"):
            st.json(result)

        st.subheader("Was this decision right?")
        f1, f2 = st.columns([3, 1])
        with f1:
            correct = st.segmented_control("Correct decision", ["allow", "review", "block"],
                                           default=result["verdict"], key="correct")
        with f2:
            st.write("")
            if st.button("Send feedback"):
                fb = gateway("/feedback", {"id": result["id"], "text": st.session_state["result_text"],
                                           "predicted_verdict": result["verdict"],
                                           "correct_verdict": correct or result["verdict"],
                                           "moderator": "demo"})
                if fb:
                    st.success("Saved. Corrections become training labels; Grafana tracks the agreement rate.")

# ----------------------------------------------------------------- Live stream
with tab_live:
    @st.fragment(run_every=5)
    def live_feed() -> None:
        df = recent_predictions()
        if df is None or df.empty:
            st.info("No streamed comments yet. Start the stream with `.\\make.ps1 stream` "
                    "(the consumer writes every prediction to Postgres).")
            return
        df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(DISPLAY_TZ).dt.tz_localize(None)
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Comments (latest window)", len(df))
        k2.metric("Blocked", f"{(df.verdict == 'block').mean():.0%}")
        k3.metric("Sent to review", f"{(df.verdict == 'review').mean():.0%}")
        k4.metric("From the drift stream", f"{(df.source == 'drift').mean():.0%}")

        per_min = (df.assign(minute=df.ts.dt.floor("min").dt.strftime("%H:%M")).groupby(["minute", "verdict"])
                   .size().reset_index(name="comments"))
        chart = alt.Chart(per_min).mark_bar().encode(
            x=alt.X("minute:O", title=f"time ({DISPLAY_TZ})", sort="ascending"),
            y=alt.Y("comments:Q", title="comments per minute"),
            color=alt.Color("verdict:N", scale=alt.Scale(domain=["allow", "review", "block"],
                                                         range=["#16a34a", "#d97706", "#dc2626"])),
            tooltip=["minute:O", "verdict:N", "comments:Q"],
        ).properties(height=220)
        st.altair_chart(chart, use_container_width=True)

        st.dataframe(
            df.head(25)[["ts", "verdict", "toxicity", "spam", "language", "source", "text"]],
            hide_index=True, use_container_width=True,
            column_config={
                "ts": st.column_config.DatetimeColumn(f"time ({DISPLAY_TZ})", format="HH:mm:ss"),
                "toxicity": st.column_config.ProgressColumn("toxicity", min_value=0, max_value=1, format="%.2f"),
                "spam": st.column_config.ProgressColumn("spam", min_value=0, max_value=1, format="%.2f"),
                "text": st.column_config.TextColumn("comment (personal data masked)", width="large"),
            })
        st.caption("Refreshes every 5 seconds. Switch to newer comments with `.\\make.ps1 drift` and watch the "
                   "mix change.")

    live_feed()

# ----------------------------------------------------------------- Review queue
with tab_review:
    st.markdown("**Review** means the gateway was not sure enough to decide alone: a toxicity score between "
                "0.5 and 0.85, a spam score between 0.6 and 0.9, or a comment that is not in English. "
                "Those comments wait here for a person. Each decision is saved as feedback: it becomes a "
                "training label, and Grafana tracks how often moderators agree with the model.")

    @st.fragment
    def review_panel() -> None:
        queue, waiting, decided = review_queue()
        if queue is None:
            st.info("The prediction log is not reachable yet. Start the stream with `.\\make.ps1 stream`.")
            return
        k1, k2 = st.columns(2)
        k1.metric("Waiting for a moderator", waiting)
        k2.metric("Decided so far", decided)
        if queue.empty:
            st.success("Nothing waiting. New uncertain comments appear here as the stream runs.")
            return
        st.caption(f"Oldest first, {len(queue)} shown.")
        for row in queue.itertuples(index=False):
            with st.container(border=True):
                c1, c2, c3 = st.columns([6, 1, 1], vertical_alignment="center")
                c1.markdown(f"{html.escape(row.text)}  \n:gray[{review_reason(row)}]")
                for col, verdict, kind in ((c2, "allow", "secondary"), (c3, "block", "primary")):
                    if col.button(verdict.capitalize(), key=f"{verdict}-{row.id}", type=kind,
                                  use_container_width=True):
                        if gateway("/feedback", {"id": row.id, "text": row.text, "predicted_verdict": "review",
                                                 "correct_verdict": verdict, "moderator": "console"}):
                            st.toast(f"{verdict.capitalize()}ed. Saved as feedback.")
                            st.rerun(scope="fragment")

    review_panel()

# ----------------------------------------------------------------- Models
with tab_models:
    models = mlflow_models()
    if not models:
        st.info("No registered models found in MLflow yet. Run `.\\make.ps1 bootstrap` once.")
    else:
        st.markdown("Every trained model is a **version** in the MLflow registry. Serving loads the version "
                    "tagged **champion**; the canary loads **challenger**. Promoting or rolling back a model "
                    "only moves a tag.")
        st.dataframe(pd.DataFrame(models), hide_index=True, use_container_width=True,
                     column_config={c: st.column_config.NumberColumn(format="%.3f")
                                    for c in ["AUC", "F1", "precision", "recall", "worst FPR gap"]})

    st.subheader("How good is the toxicity champion?")
    eval_dir = MODELS_DIR / "toxicity" / "champion" / "evaluation"
    charts = [("roc_curve.png", "ROC curve"), ("confusion_matrix.png", "Confusion matrix"),
              ("score_distribution.png", "Score distribution"), ("top_ngrams.png", "What it learned")]
    found = [(eval_dir / f, cap) for f, cap in charts if (eval_dir / f).exists()]
    if not found:
        st.info("Evaluation charts appear here after training (`.\\make.ps1 bootstrap`).")
    else:
        cols = st.columns(2)
        for i, (path, cap) in enumerate(found):
            cols[i % 2].image(str(path), caption=cap, use_container_width=True)

# ----------------------------------------------------------------- Fairness
with tab_fair:
    st.markdown("Annotators labelled some harmless comments that mention certain groups as toxic. A model "
                "trained on those labels learns that *naming a group* is toxic. We measure how often harmless "
                "comments about each group get flagged, before and after bias mitigation (identity-term "
                "masking plus re-weighting).")
    before = load_json(REPORTS_DIR / "fairness_champion_unmitigated.json")
    after = load_json(REPORTS_DIR / "fairness_champion.json")
    if not (before and after):
        st.info("Fairness results appear here after training (`.\\make.ps1 bootstrap`).")
    else:
        m1, m2, m3 = st.columns(3)
        m1.metric("Worst false-positive gap", f"{after['worst_fpr_gap']:.2f}",
                  f"{after['worst_fpr_gap'] - before['worst_fpr_gap']:+.2f} vs no mitigation", delta_color="inverse")
        m2.metric("Overall AUC", f"{after['overall_auc']:.3f}",
                  f"{after['overall_auc'] - before['overall_auc']:+.3f} vs no mitigation", delta_color="normal")
        m3.metric("Final bias score (Jigsaw)", f"{after['final_bias_score']:.3f}")
        models_order = ["without mitigation", "with mitigation (champion)"]
        rows = []
        for name, res in zip(models_order, (before, after), strict=True):
            for group, v in res["fpr_by_group"].items():
                label = "no group named" if group == "no_identity" else group.replace("_", " ")
                rows.append({"group": label, "model": name, "rate": v})
        data = pd.DataFrame(rows)
        order = (data[data.model == models_order[0]].sort_values("rate", ascending=False)["group"].tolist())
        base = alt.Chart(data).encode(
            y=alt.Y("group:N", title=None, sort=order, axis=alt.Axis(labelLimit=260)),
            yOffset=alt.YOffset("model:N", sort=models_order),
            x=alt.X("rate:Q", title="false-positive rate: share of harmless comments flagged as toxic",
                    scale=alt.Scale(domain=[0, max(0.1, data.rate.max() * 1.15)])),
            color=alt.Color("model:N", sort=models_order, title=None, legend=alt.Legend(orient="top"),
                            scale=alt.Scale(domain=models_order, range=["#dc2626", "#2563eb"])),
            tooltip=["group", "model", alt.Tooltip("rate:Q", format=".2f")],
        )
        bars = base.mark_bar(height=9)
        labels = base.mark_text(align="left", dx=4, fontSize=11).encode(text=alt.Text("rate:Q", format=".2f"))
        st.altair_chart((bars + labels).properties(height=46 * data.group.nunique()), use_container_width=True)
        st.caption("Red: the model trained on the biased labels. Blue: after mitigation. "
                   "0.00 means no harmless comment about that group was flagged.")
        gate = load_json(REPORTS_DIR / "gate_toxicity.json")
        if gate:
            st.subheader("Quality gate (a new model must be at least as accurate and at least as fair)")
            for c in gate["checks"]:
                st.markdown(f"{'✅' if c['passed'] else '❌'} **{c['check']}**: {c['detail']}")

# ----------------------------------------------------------------- System
with tab_sys:
    st.markdown("Open each tool in a new tab. What to show in each:")
    status = tool_status()
    for name, _, url, what in TOOLS:
        st.markdown(f"{'🟢' if status.get(name) else '🔴'} **[{name}]({url})**: {what}")
    st.caption("Logins: Airflow admin / admin · Grafana admin / admin. A red dot means the service is not "
               "reachable yet (it may still be starting).")
