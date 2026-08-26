#!/usr/bin/env bash
set -euo pipefail

KUBECONFIG_PATH="${KUBECONFIG_PATH:-terraform/omega.kubeconfig}"
NAMESPACE="${NAMESPACE:-paprika-e2e}"
SECRET_NAME="${SECRET_NAME:-skunkworq-ghcr}"
REGISTRY="${REGISTRY:-ghcr.io}"
IMAGE="${IMAGE:-ghcr.io/skunkworq/uptime/api:latest}"
CHECK_POD="${CHECK_POD:-ghcr-pull-check}"

if [[ -z "${GHCR_USERNAME:-}" ]]; then
  echo "GHCR_USERNAME is required" >&2
  exit 1
fi

if [[ -z "${GHCR_TOKEN:-}" ]]; then
  echo "GHCR_TOKEN is required; use a GitHub token with read:packages and package access" >&2
  exit 1
fi

tmp_secret="$(mktemp)"
tmp_pod="$(mktemp)"
trap 'rm -f "$tmp_secret" "$tmp_pod"' EXIT

kubectl --kubeconfig="$KUBECONFIG_PATH" -n "$NAMESPACE" create secret docker-registry "$SECRET_NAME" \
  --docker-server="$REGISTRY" \
  --docker-username="$GHCR_USERNAME" \
  --docker-password="$GHCR_TOKEN" \
  --dry-run=client -o yaml >"$tmp_secret"

if kubectl --kubeconfig="$KUBECONFIG_PATH" -n "$NAMESPACE" get secret "$SECRET_NAME" >/dev/null 2>&1; then
  kubectl --kubeconfig="$KUBECONFIG_PATH" -n "$NAMESPACE" replace -f "$tmp_secret" >/dev/null
  action="replaced"
else
  kubectl --kubeconfig="$KUBECONFIG_PATH" -n "$NAMESPACE" create -f "$tmp_secret" >/dev/null
  action="created"
fi

kubectl --kubeconfig="$KUBECONFIG_PATH" -n "$NAMESPACE" label secret "$SECRET_NAME" \
  app.kubernetes.io/part-of=telesis \
  app.kubernetes.io/component=image-pull \
  app.kubernetes.io/managed-by=manual-seed \
  --overwrite >/dev/null

echo "$action image pull secret $NAMESPACE/$SECRET_NAME for $REGISTRY"

kubectl --kubeconfig="$KUBECONFIG_PATH" -n "$NAMESPACE" delete pod "$CHECK_POD" --ignore-not-found >/dev/null

cat >"$tmp_pod" <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: $CHECK_POD
  namespace: $NAMESPACE
  labels:
    app.kubernetes.io/part-of: telesis
    app.kubernetes.io/component: image-pull-check
spec:
  restartPolicy: Never
  imagePullSecrets:
    - name: $SECRET_NAME
  containers:
    - name: pull-check
      image: $IMAGE
      imagePullPolicy: Always
EOF

kubectl --kubeconfig="$KUBECONFIG_PATH" apply -f "$tmp_pod" >/dev/null

deadline=$((SECONDS + 120))
while (( SECONDS < deadline )); do
  pod_json="$(kubectl --kubeconfig="$KUBECONFIG_PATH" -n "$NAMESPACE" get pod "$CHECK_POD" -o json)"
  image_id="$(jq -r '.status.containerStatuses[0].imageID // ""' <<<"$pod_json")"
  wait_reason="$(jq -r '.status.containerStatuses[0].state.waiting.reason // ""' <<<"$pod_json")"

  if [[ -n "$image_id" ]]; then
    echo "validated pull for $IMAGE"
    kubectl --kubeconfig="$KUBECONFIG_PATH" -n "$NAMESPACE" delete pod "$CHECK_POD" --ignore-not-found >/dev/null
    exit 0
  fi

  case "$wait_reason" in
    ErrImagePull|ImagePullBackOff)
      echo "image pull failed for $IMAGE" >&2
      kubectl --kubeconfig="$KUBECONFIG_PATH" -n "$NAMESPACE" describe pod "$CHECK_POD" >&2
      exit 1
      ;;
  esac

  sleep 5
done

echo "timed out waiting for image pull validation for $IMAGE" >&2
kubectl --kubeconfig="$KUBECONFIG_PATH" -n "$NAMESPACE" describe pod "$CHECK_POD" >&2
exit 1
