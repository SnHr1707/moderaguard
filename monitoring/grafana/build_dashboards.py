"""Generate the Grafana dashboards as JSON (owner: M7).

Dashboards are code: edit the panels here, run this script, and commit the
JSON in monitoring/grafana/dashboards/. Grafana loads them on start.

Run:  python monitoring/grafana/build_dashboards.py
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).parent / "dashboards"
DS = {"type": "prometheus", "uid": "prometheus"}


def panel(pid, title, targets, x, y, w=12, h=8, kind="timeseries", unit=None, description="",
          thresholds=None, minv=None, maxv=None):
    defaults = {"unit": unit} if unit else {}
    if minv is not None:
        defaults["min"] = minv
    if maxv is not None:
        defaults["max"] = maxv
    if thresholds:
        defaults["thresholds"] = {"mode": "absolute", "steps": thresholds}
        defaults["custom"] = {"thresholdsStyle": {"mode": "line+area"}} if kind == "timeseries" else {}
    return {
        "id": pid, "type": kind, "title": title, "description": description, "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}} if kind == "timeseries" else {},
        "targets": [{"refId": chr(65 + i), "datasource": DS, "expr": expr, "legendFormat": legend}
                    for i, (expr, legend) in enumerate(targets)],
    }


def dashboard(uid, title, panels, description):
    return {"uid": uid, "title": title, "description": description, "tags": ["moderaguard"],
            "timezone": "browser", "schemaVersion": 39, "refresh": "10s",
            "time": {"from": "now-1h", "to": "now"}, "panels": panels}


service = dashboard("mg-service", "ModeraGuard / Service health", [
    panel(1, "Requests per second by service and variant",
          [('sum by (service, variant) (rate(moderaguard_requests_total{endpoint=~"/moderate|/predict"}[1m]))',
            "{{service}} {{variant}}")], 0, 0, unit="reqps"),
    panel(2, "p95 latency", [
        ('histogram_quantile(0.95, sum by (le, service) (rate(moderaguard_latency_seconds_bucket'
         '{endpoint=~"/moderate|/predict"}[5m])))', "{{service}}")], 12, 0, unit="s",
        thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 0.5}]),
    panel(3, "Error rate (5xx share)", [
        # "or ... * 0" shows 0 instead of "No data" while nothing has failed
        ('(sum by (service) (rate(moderaguard_requests_total{status=~"5.."}[5m])) '
         'or sum by (service) (rate(moderaguard_requests_total[5m])) * 0) / '
         'sum by (service) (rate(moderaguard_requests_total[5m]))', "{{service}}")], 0, 8, unit="percentunit",
        thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 0.05}]),
    panel(4, "Services up", [('up{job="moderaguard-services"}', "{{service}}")], 12, 8, kind="stat",
          thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 1}]),
    panel(5, "Loaded model versions", [("moderaguard_model_info", "{{service}} {{variant}}: {{version}}")],
          0, 16, w=24, h=6, kind="table"),
], "Traffic, latency, errors and availability of the gateway and model services.")

model = dashboard("mg-model", "ModeraGuard / Models, canary and drift", [
    panel(1, "Verdict mix: stable vs canary", [
        ('sum by (variant, verdict) (rate(moderaguard_verdicts_total[5m])) / ignoring(verdict) group_left '
         'sum by (variant) (rate(moderaguard_verdicts_total[5m]))', "{{variant}} {{verdict}}")],
          0, 0, unit="percentunit", minv=0, maxv=1,
          description="Share of allow/review/block per deployment. A canary that behaves very differently "
                      "from stable is a reason to stop the rollout."),
    panel(2, "Average model score by variant", [
        ('sum by (model, variant) (rate(moderaguard_score_sum[5m])) / '
         'sum by (model, variant) (rate(moderaguard_score_count[5m]))', "{{model}} {{variant}}")],
          12, 0, minv=0, maxv=1, description="Prediction drift shows up here first."),
    panel(3, "Drifted feature share (Evidently)", [("moderaguard_drift_share", "drift share")], 0, 8,
          unit="percentunit", minv=0, maxv=1,
          thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 0.3}],
          description="Above the red line Alertmanager fires ModelDriftDetected and retraining starts."),
    panel(4, "Drift test p-value per feature (lower = more drift)",
          [("moderaguard_drift_p_value", "{{feature}}")], 12, 8, minv=0, maxv=1,
          thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 0.05}]),
    panel(5, "Languages detected", [("sum by (language) (rate(moderaguard_languages_total[5m]))",
                                     "{{language}}")], 0, 16, unit="reqps"),
    panel(6, "Moderator agreement", [
        ('sum(rate(moderaguard_feedback_total{agreed="true"}[1h])) / sum(rate(moderaguard_feedback_total[1h]))',
         "agreement")], 12, 16, kind="stat", unit="percentunit",
          thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 0.7}]),
    panel(7, "Verdict reasons", [("sum by (reason) (rate(moderaguard_verdicts_total[5m]))", "{{reason}}")],
          0, 24, w=24, unit="reqps"),
], "Model behaviour per deployment variant, drift detection and moderator feedback.")

infra = dashboard("mg-infra", "ModeraGuard / Server and database", [
    panel(1, "CPU used", [('1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m]))', "cpu")], 0, 0,
          unit="percentunit", minv=0, maxv=1),
    panel(2, "Memory used", [("1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes", "memory")],
          12, 0, unit="percentunit", minv=0, maxv=1),
    panel(3, "Postgres up", [("pg_up", "postgres")], 0, 8, kind="stat",
          thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 1}]),
    panel(4, "Database transactions per second",
          [('sum by (datname) (rate(pg_stat_database_xact_commit{datname=~"moderaguard|mlflow|airflow"}[5m]))',
            "{{datname}}")], 12, 8, unit="ops"),
    panel(5, "Database size", [('pg_database_size_bytes{datname=~"moderaguard|mlflow|airflow"}', "{{datname}}")],
          0, 16, unit="bytes"),
    panel(6, "Rows written to the prediction log per second",
          [('rate(pg_stat_database_tup_inserted{datname="moderaguard"}[5m])', "inserts")], 12, 16, unit="ops"),
], "Host and Postgres health (node-exporter and postgres-exporter).")

OUT.mkdir(parents=True, exist_ok=True)
for name, dash in (("service-health", service), ("models-canary-drift", model), ("server-database", infra)):
    (OUT / f"{name}.json").write_text(json.dumps(dash, indent=2) + "\n")
    print(f"wrote {OUT / name}.json")
