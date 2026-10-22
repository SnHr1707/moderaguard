#!/usr/bin/env bash
# Finish a canary (owner: M6).
#   end-canary.sh promote   challenger becomes champion, stable pods reload it
#   end-canary.sh rollback  canary removed, champion untouched
# MLFLOW_TRACKING_URI must point at MLflow for "promote".
set -euo pipefail
MODE=${1:?usage: end-canary.sh promote|rollback}
NS=${NAMESPACE:-moderaguard}
HERE=$(cd "$(dirname "$0")" && pwd)

if [ "$MODE" = promote ]; then
  python -m moderaguard.models.register promote --task toxicity
  # stable pods load models:/moderaguard-toxicity@champion again on start
  kubectl -n "$NS" rollout restart deployment/toxicity-svc
  kubectl -n "$NS" rollout status deployment/toxicity-svc --timeout=180s
fi

# Restore the plain route first so no request is sent to a deleted service.
# Only the routing file is applied: re-applying the whole overlay from a fresh
# checkout would reset the stable images to their placeholder tags.
kubectl -n "$NS" apply -f "$HERE/../overlays/cloud/gateway-api.yaml"
kubectl -n "$NS" delete deployment,service -l track=canary --ignore-not-found
echo "canary ended: $MODE"
