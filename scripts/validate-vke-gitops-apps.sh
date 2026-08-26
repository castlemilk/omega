#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
projects_dir="${PROJECTS_DIR:-${HOME}/projects}"
kubeconfig="${KUBECONFIG:-${root_dir}/terraform/omega.kubeconfig}"
namespace="${PAPRIKA_NAMESPACE:-paprika-e2e}"

apps=(
  telesis-api
  brandbrain-api
  cuttlefish-controlplane
  flaggr-api
)

manifests=(
  "${projects_dir}/uptime/deploy/kubernetes/paprika/application.yaml"
  "${projects_dir}/brandbrain/deploy/kubernetes/paprika/application.yaml"
  "${projects_dir}/cuttlefish/deploy/kubernetes/paprika/application.yaml"
  "${projects_dir}/flaggr/deploy/kubernetes/paprika/application.yaml"
)

source_expectations=(
  "telesis-api|https://github.com/skunkworq/uptime.git|deploy/kubernetes/chart"
  "brandbrain-api|https://github.com/skunkworq/brandbrain.git|deploy/kubernetes/chart"
  "cuttlefish-controlplane|https://github.com/skunkworq/cuttlefish.git|deploy/kubernetes/chart"
  "flaggr-api|https://github.com/skunkworq/flaggr.git|deploy/kubernetes/chart"
)

required_secrets=(
  "telesis-gar:.dockerconfigjson"
  "telesis-api-env:DATABASE_URL,FIREBASE_PROJECT_ID,FRONTEND_BASE_URL,RESEND_API_KEY,RESEND_FROM_EMAIL,RESEND_FROM_NAME"
  "brandbrain-gar:.dockerconfigjson"
  "brandbrain-api-env:DATABASE_URL,GOOGLE_CLIENT_ID,GOOGLE_CLIENT_SECRET,OPENAI_API_KEY"
  "cuttlefish-gar:.dockerconfigjson"
  "cuttlefish-controlplane-env:DATABASE_URL,AUTH_BOOTSTRAP_TOKEN,AUTH_SESSION_SECRET,FIREBASE_API_KEY,CI_GITHUB_APP_ID,CI_GITHUB_APP_PRIVATE_KEY_PEM,CI_GITHUB_APP_WEBHOOK_SECRET,PIPELINE_OIDC_PRIVATE_KEY_PEM,RUNNER_ENDPOINT_TOKEN,SECRET_ENCRYPTION_KEY"
  "flaggr-gar:.dockerconfigjson"
)

workload_identity_apps=(
  "telesis-api|1070169189903|telesis-vke-runtime@uptime-485903.iam.gserviceaccount.com"
  "brandbrain-api|976998755879|brandbrain-backend@brandbrain-486909.iam.gserviceaccount.com"
  "cuttlefish-controlplane|698099003913|cf-controlplane@cuttlefish-d16cd.iam.gserviceaccount.com"
  "flaggr-api|92803451840|flaggr-grpc-sa@flaggr-478302.iam.gserviceaccount.com"
)

echo "==> Server-side dry-run app-owned Application manifests"
for manifest in "${manifests[@]}"; do
  kubectl --kubeconfig="${kubeconfig}" apply --dry-run=server -f "${manifest}" >/dev/null
  echo "ok ${manifest}"
done

echo "==> Ensuring app manifests do not shadow chart-owned image versions"
if rg -n '^\s*([A-Za-z0-9_.-]+\.)?image\.(repository|tag|digest):' "${manifests[@]}"; then
  echo "image repository/tag/digest overrides belong in chart values.yaml, not Paprika Application parameters" >&2
  exit 1
fi
echo "ok no image version overrides in Application manifests"

echo "==> Ensuring Google runtime credentials are keyless"
if rg -n '(gcpCredentials\.|firebaseAdmin\.(existingSecret|key)|google-application-credentials|firebase-admin-key\.json)' "${manifests[@]}"; then
  echo "Google runtime credentials must use workloadIdentity.*, not mounted JSON key secrets" >&2
  exit 1
fi
echo "ok no Google JSON-key runtime wiring in Application manifests"

echo "==> Checking live Paprika Application autosync settings"
for item in "${source_expectations[@]}"; do
  IFS='|' read -r app repo_url source_path <<< "${item}"
  source_type="$(kubectl --kubeconfig="${kubeconfig}" -n "${namespace}" get application "${app}" -o jsonpath='{.spec.source.type}')"
  actual_repo_url="$(kubectl --kubeconfig="${kubeconfig}" -n "${namespace}" get application "${app}" -o jsonpath='{.spec.source.repoUrl}')"
  actual_source_path="$(kubectl --kubeconfig="${kubeconfig}" -n "${namespace}" get application "${app}" -o jsonpath='{.spec.source.path}')"
  revision="$(kubectl --kubeconfig="${kubeconfig}" -n "${namespace}" get application "${app}" -o jsonpath='{.spec.source.revision}')"
  poll_interval="$(kubectl --kubeconfig="${kubeconfig}" -n "${namespace}" get application "${app}" -o jsonpath='{.spec.source.pollInterval}')"
  sync_policy="$(kubectl --kubeconfig="${kubeconfig}" -n "${namespace}" get application "${app}" -o jsonpath='{.spec.syncPolicy}')"
  synced="$(kubectl --kubeconfig="${kubeconfig}" -n "${namespace}" get application "${app}" -o jsonpath='{.status.synced}')"
  health="$(kubectl --kubeconfig="${kubeconfig}" -n "${namespace}" get application "${app}" -o jsonpath='{.status.health}')"

  if [[ "${source_type}" != "git" || "${actual_repo_url}" != "${repo_url}" || "${actual_source_path}" != "${source_path}" || "${revision}" != "main" || "${poll_interval}" != "60s" || "${sync_policy}" != "Auto" ]]; then
    echo "bad autosync settings for ${app}: type=${source_type} repo=${actual_repo_url} path=${actual_source_path} revision=${revision} poll=${poll_interval} sync=${sync_policy}" >&2
    exit 1
  fi
  if [[ "${synced}" != "true" || "${health}" != "Healthy" ]]; then
    echo "app ${app} not healthy/synced: synced=${synced} health=${health}" >&2
    exit 1
  fi
  echo "ok ${app} ${repo_url}/${source_path} Auto poll=60s healthy synced"
done

echo "==> Checking live Workload Identity settings"
for item in "${workload_identity_apps[@]}"; do
  IFS='|' read -r app project_number service_account_email <<< "${item}"
  enabled="$(kubectl --kubeconfig="${kubeconfig}" -n "${namespace}" get application "${app}" -o jsonpath='{.spec.parameters.workloadIdentity\.enabled}')"
  actual_project_number="$(kubectl --kubeconfig="${kubeconfig}" -n "${namespace}" get application "${app}" -o jsonpath='{.spec.parameters.workloadIdentity\.projectNumber}')"
  actual_pool="$(kubectl --kubeconfig="${kubeconfig}" -n "${namespace}" get application "${app}" -o jsonpath='{.spec.parameters.workloadIdentity\.pool}')"
  actual_provider="$(kubectl --kubeconfig="${kubeconfig}" -n "${namespace}" get application "${app}" -o jsonpath='{.spec.parameters.workloadIdentity\.provider}')"
  actual_service_account_email="$(kubectl --kubeconfig="${kubeconfig}" -n "${namespace}" get application "${app}" -o jsonpath='{.spec.parameters.workloadIdentity\.serviceAccountEmail}')"

  if [[ "${enabled}" != "true" || "${actual_project_number}" != "${project_number}" || "${actual_pool}" != "vke-omega" || "${actual_provider}" != "omega" || "${actual_service_account_email}" != "${service_account_email}" ]]; then
    echo "bad workload identity settings for ${app}: enabled=${enabled} projectNumber=${actual_project_number} pool=${actual_pool} provider=${actual_provider} serviceAccountEmail=${actual_service_account_email}" >&2
    exit 1
  fi
  echo "ok ${app} WIF ${project_number}/${service_account_email}"
done

echo "==> Checking referenced runtime and pull secrets"
for item in "${required_secrets[@]}"; do
  name="${item%%:*}"
  key_csv="${item#*:}"
  kubectl --kubeconfig="${kubeconfig}" -n "${namespace}" get secret "${name}" >/dev/null
  IFS=',' read -r -a keys <<< "${key_csv}"
  for key in "${keys[@]}"; do
    if ! kubectl --kubeconfig="${kubeconfig}" -n "${namespace}" get secret "${name}" -o json \
      | jq -e --arg key "${key}" '.data[$key] != null' >/dev/null; then
      echo "secret ${name} is missing key ${key}" >&2
      exit 1
    fi
  done
  echo "ok secret ${name}"
done

echo "==> VKE GitOps app validation passed"
