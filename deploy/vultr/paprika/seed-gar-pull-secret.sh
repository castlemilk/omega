#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-uptime-485903}"
REGION="${REGION:-australia-southeast1}"
REPOSITORY="${REPOSITORY:-uptime-prod-docker}"
SERVICE_ACCOUNT_ID="${SERVICE_ACCOUNT_ID:-vultr-telesis-pull}"
NAMESPACE="${NAMESPACE:-paprika-e2e}"
SECRET_NAME="${SECRET_NAME:-telesis-gar}"
KUBECONFIG_PATH="${KUBECONFIG_PATH:-terraform/omega.kubeconfig}"
IMAGE="${IMAGE:-${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/api:ab2d5b3}"
CHECK_POD="${CHECK_POD:-gar-pull-check}"

REGISTRY="${REGION}-docker.pkg.dev"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_ID}@${PROJECT_ID}.iam.gserviceaccount.com"

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

key_file="${tmpdir}/key.json"
docker_config="${tmpdir}/dockerconfig.json"
secret_yaml="${tmpdir}/secret.yaml"
pod_yaml="${tmpdir}/pod.yaml"

if ! gcloud iam service-accounts describe "${SERVICE_ACCOUNT_EMAIL}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${SERVICE_ACCOUNT_ID}" \
    --project="${PROJECT_ID}" \
    --display-name="Vultr Telesis image pull" >/dev/null
  echo "created service account ${SERVICE_ACCOUNT_EMAIL}"
else
  echo "service account exists ${SERVICE_ACCOUNT_EMAIL}"
fi

gcloud artifacts repositories add-iam-policy-binding "${REPOSITORY}" \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
  --role="roles/artifactregistry.reader" >/dev/null

gcloud iam service-accounts keys create "${key_file}" \
  --iam-account="${SERVICE_ACCOUNT_EMAIL}" \
  --project="${PROJECT_ID}" >/dev/null

auth="$(printf "_json_key:%s" "$(cat "${key_file}")" | base64 | tr -d "\n")"
jq -n \
  --arg registry "${REGISTRY}" \
  --arg auth "${auth}" \
  --rawfile password "${key_file}" \
  '{auths:{($registry):{username:"_json_key",password:$password,auth:$auth}}}' >"${docker_config}"

kubectl --kubeconfig="${KUBECONFIG_PATH}" -n "${NAMESPACE}" create secret generic "${SECRET_NAME}" \
  --type=kubernetes.io/dockerconfigjson \
  --from-file=.dockerconfigjson="${docker_config}" \
  --dry-run=client -o yaml >"${secret_yaml}"

if kubectl --kubeconfig="${KUBECONFIG_PATH}" -n "${NAMESPACE}" get secret "${SECRET_NAME}" >/dev/null 2>&1; then
  kubectl --kubeconfig="${KUBECONFIG_PATH}" -n "${NAMESPACE}" replace -f "${secret_yaml}" >/dev/null
  action="replaced"
else
  kubectl --kubeconfig="${KUBECONFIG_PATH}" -n "${NAMESPACE}" create -f "${secret_yaml}" >/dev/null
  action="created"
fi

kubectl --kubeconfig="${KUBECONFIG_PATH}" -n "${NAMESPACE}" label secret "${SECRET_NAME}" \
  app.kubernetes.io/part-of=telesis \
  app.kubernetes.io/component=image-pull \
  app.kubernetes.io/managed-by=manual-seed \
  cloud.google.com/project="${PROJECT_ID}" \
  --overwrite >/dev/null

meta="$(kubectl --kubeconfig="${KUBECONFIG_PATH}" -n "${NAMESPACE}" get secret "${SECRET_NAME}" -o json | jq -r '.type + " annotations=" + (((.metadata.annotations // {})|keys)|join(",")) + " auths=" + ((.data[".dockerconfigjson"]|@base64d|fromjson|.auths|keys)|join(","))')"
echo "${action} ${NAMESPACE}/${SECRET_NAME} ${meta}"

kubectl --kubeconfig="${KUBECONFIG_PATH}" -n "${NAMESPACE}" delete pod "${CHECK_POD}" --ignore-not-found >/dev/null

cat >"${pod_yaml}" <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: ${CHECK_POD}
  namespace: ${NAMESPACE}
  labels:
    app.kubernetes.io/part-of: telesis
    app.kubernetes.io/component: image-pull-check
spec:
  restartPolicy: Never
  imagePullSecrets:
    - name: ${SECRET_NAME}
  containers:
    - name: pull-check
      image: ${IMAGE}
      imagePullPolicy: Always
EOF

kubectl --kubeconfig="${KUBECONFIG_PATH}" apply -f "${pod_yaml}" >/dev/null

deadline=$((SECONDS + 120))
while (( SECONDS < deadline )); do
  pod_json="$(kubectl --kubeconfig="${KUBECONFIG_PATH}" -n "${NAMESPACE}" get pod "${CHECK_POD}" -o json)"
  image_id="$(jq -r '.status.containerStatuses[0].imageID // ""' <<<"${pod_json}")"
  wait_reason="$(jq -r '.status.containerStatuses[0].state.waiting.reason // ""' <<<"${pod_json}")"

  if [[ -n "${image_id}" ]]; then
    echo "validated pull for ${IMAGE}"
    kubectl --kubeconfig="${KUBECONFIG_PATH}" -n "${NAMESPACE}" delete pod "${CHECK_POD}" --ignore-not-found >/dev/null
    exit 0
  fi

  case "${wait_reason}" in
    ErrImagePull|ImagePullBackOff)
      echo "image pull failed for ${IMAGE}" >&2
      kubectl --kubeconfig="${KUBECONFIG_PATH}" -n "${NAMESPACE}" describe pod "${CHECK_POD}" >&2
      exit 1
      ;;
  esac

  sleep 5
done

echo "timed out waiting for image pull validation for ${IMAGE}" >&2
kubectl --kubeconfig="${KUBECONFIG_PATH}" -n "${NAMESPACE}" describe pod "${CHECK_POD}" >&2
exit 1
