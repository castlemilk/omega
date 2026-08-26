# Vultr Paprika Cluster Config

This directory owns cluster-specific wiring for the omega Vultr/VKE Paprika environment.
Paprika itself should not carry workload manifests for BrandBrain, Cuttlefish, Flaggr, or Telesis.

Files here are safe/idempotent cluster bootstrap inputs:

- `omega-gateway.yaml`, `omega-referencegrant.yaml`, `omega-tls.yaml`: Gateway API routing and TLS references.
- `envoy-gateway-svc-alias.yaml`, `envoy-proxy.yaml`: Envoy Gateway service/proxy customization.
- `cert-manager-values.yaml`: cert-manager install values.
- `seed-gar-pull-secret.sh`, `seed-ghcr-pull-secret.sh`: pull-secret bootstrap helpers.

App-owned Paprika `Application` manifests live with their source repos:

- `~/projects/brandbrain/deploy/kubernetes/paprika/application.yaml`
- `~/projects/cuttlefish/deploy/kubernetes/paprika/application.yaml`
- `~/projects/flaggr/deploy/kubernetes/paprika/application.yaml`
- `~/projects/uptime/deploy/kubernetes/paprika/application.yaml`

Apply app manifests from those repos after their chart and workflow changes are merged.
