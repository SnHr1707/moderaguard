#!/usr/bin/env bash
# One-time setup of the cloud VM (owner: M6). Tested target: Ubuntu 24.04,
# 4 vCPU / 16 GB RAM, ports 22, 80, 3000, 5000, 8080, 8081 open in the firewall.
#
#   git clone <your repo> ~/moderaguard && cd ~/moderaguard
#   sudo bash infra/cloud/setup-vm.sh
#
# Installs Docker, k3s (with Traefik's Gateway API provider), a private image
# registry on :5001 that Jenkins pushes to and k3s pulls from, and Jenkins.
set -euo pipefail

REPO_DIR=$(cd "$(dirname "$0")/../.." && pwd)
VM_IP=$(hostname -I | awk '{print $1}')
echo "== VM private IP: $VM_IP"

echo "== 1/6 Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
usermod -aG docker "${SUDO_USER:-$USER}" || true

echo "== 2/6 private image registry on :5001"
docker run -d --restart=always --name registry -p 5001:5000 -v registry-data:/var/lib/registry registry:2 2>/dev/null \
  || echo "registry already running"

echo "== 3/6 k3s (Traefik with the Gateway API provider)"
mkdir -p /etc/rancher/k3s /var/lib/rancher/k3s/server/manifests
cat > /etc/rancher/k3s/registries.yaml <<EOF
mirrors:
  "localhost:5001":
    endpoint: ["http://localhost:5001"]
EOF
cp "$REPO_DIR/infra/cloud/traefik-config.yaml" /var/lib/rancher/k3s/server/manifests/traefik-config.yaml
if ! command -v k3s >/dev/null; then
  curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--write-kubeconfig-mode 644" sh -
fi
until kubectl get nodes >/dev/null 2>&1; do sleep 3; done
kubectl wait --for=condition=Ready node --all --timeout=180s

# kubeconfig that works from inside containers (Jenkins), using the VM IP instead of 127.0.0.1
sed "s/127.0.0.1/$VM_IP/" /etc/rancher/k3s/k3s.yaml > "$REPO_DIR/infra/cloud/kubeconfig-vm.yaml"
chmod 600 "$REPO_DIR/infra/cloud/kubeconfig-vm.yaml"

echo "== 4/6 point the manifests at this VM"
sed -i "s/VM_PRIVATE_IP/$VM_IP/" "$REPO_DIR/k8s/overlays/cloud/platform.env" "$REPO_DIR/k8s/monitoring/platform.env"
[ -f "$REPO_DIR/.env" ] || cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
sed -i "s|^KAFKA_EXTERNAL_HOST=.*|KAFKA_EXTERNAL_HOST=$VM_IP|; s|^GATEWAY_URL=.*|GATEWAY_URL=http://$VM_IP|" "$REPO_DIR/.env"
grep -q '^VM_IP=' "$REPO_DIR/.env" && sed -i "s|^VM_IP=.*|VM_IP=$VM_IP|" "$REPO_DIR/.env" || echo "VM_IP=$VM_IP" >> "$REPO_DIR/.env"
sed -i "s|^JENKINS_URL=.*|JENKINS_URL=http://$VM_IP:8081|" "$REPO_DIR/.env"
# the Pushgateway runs on k3s in the cloud (NodePort 30091), not in Docker Compose
grep -q '^PUSHGATEWAY=' "$REPO_DIR/.env" && sed -i "s|^PUSHGATEWAY=.*|PUSHGATEWAY=$VM_IP:30091|" "$REPO_DIR/.env" \
  || echo "PUSHGATEWAY=$VM_IP:30091" >> "$REPO_DIR/.env"

echo "== 5/6 Kubernetes secrets"
set -a
# shellcheck source=/dev/null
. "$REPO_DIR/.env"
set +a
kubectl create namespace moderaguard --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
kubectl -n moderaguard create secret generic moderaguard-secrets \
  --from-literal=FEEDBACK_DSN="postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@$VM_IP:5432/moderaguard" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n monitoring create secret generic grafana-admin --from-literal=password="$GRAFANA_PASSWORD" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n monitoring create secret generic airflow-api --from-literal=password=admin \
  --dry-run=client -o yaml | kubectl apply -f -

echo "== 6/6 Jenkins on :8081"
docker compose --env-file "$REPO_DIR/.env" -f "$REPO_DIR/infra/jenkins/docker-compose.yml" up -d --build

cat <<EOF

Done. Next steps (README "Cloud deployment"):
  1. docker compose up -d postgres s3 s3-init mlflow kafka airflow consumer
     (in $REPO_DIR: the platform services; serving and monitoring run on k3s)
  2. docker compose run --rm trainer          # train + register the first models
  3. Open Jenkins at http://<public-ip>:8081 and run the 'moderaguard' job.
  4. make k8s-monitoring                       # Prometheus, Grafana, Alertmanager on k3s
  5. API: http://<public-ip>/docs   UI: http://<public-ip>/ui   Grafana: http://<public-ip>/grafana
EOF
