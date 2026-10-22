#!/usr/bin/env bash
# Send PERCENT of API traffic to the canary (owner: M6).
#   k8s/scripts/set-canary-weight.sh 50
set -euo pipefail
PERCENT=${1:?usage: set-canary-weight.sh <0-100>}
NS=${NAMESPACE:-moderaguard}
kubectl -n "$NS" patch httproute api --type=json -p "[
  {\"op\": \"replace\", \"path\": \"/spec/rules/2/backendRefs/0/weight\", \"value\": $((100 - PERCENT))},
  {\"op\": \"replace\", \"path\": \"/spec/rules/2/backendRefs/1/weight\", \"value\": $PERCENT}
]"
echo "canary now receives ${PERCENT}% of API traffic"
