# Paprika VKE GitOps Apps

Date: 2026-07-09

Omega owns the Vultr/VKE cluster wiring. Each workload repo owns its own Helm chart and Paprika `Application`.
Paprika should only host the open-source Paprika controller, API, UI, CRDs, and chart.

## App Ownership

| Application | Source repository | Chart path | Paprika manifest |
| --- | --- | --- | --- |
| `brandbrain-api` | `https://github.com/skunkworq/brandbrain.git` | `deploy/kubernetes/chart` | `deploy/kubernetes/paprika/application.yaml` |
| `cuttlefish-controlplane` | `https://github.com/skunkworq/cuttlefish.git` | `deploy/kubernetes/chart` | `deploy/kubernetes/paprika/application.yaml` |
| `flaggr-api` | `https://github.com/skunkworq/flaggr.git` | `deploy/kubernetes/chart` | `deploy/kubernetes/paprika/application.yaml` |
| `telesis-api` | `https://github.com/skunkworq/uptime.git` | `deploy/kubernetes/chart` | `deploy/kubernetes/paprika/application.yaml` |

## Release Flow

1. A source repo change lands on `main`.
2. The repo workflow builds and pushes immutable `linux/amd64` image tags like `sha-<12-char-sha>`.
3. The same workflow runs the in-repo chart helper at `deploy/kubernetes/chart/scripts/bump-image-tag.sh`.
4. The workflow commits `deploy/kubernetes/chart/values.yaml` back to the app repo with `[skip ci]`.
5. Paprika polls the app repo chart path, detects the chart default change, renders it, and creates the rollout.
6. The workflow waits for the live Deployment image to match the expected immutable tag, then checks public health.

This removes the previous external `paprikacd/*-chart` repositories from the release path.

## Runtime Identity

Runtime Google Cloud access should be keyless through the Vultr OIDC issuer and Google Workload Identity Federation.
The app `Application` manifests set `workloadIdentity.enabled=true` and pass the project number, pool, provider, and
Google service account email into their charts.

Cluster bootstrap and Gateway config lives in `deploy/vultr/paprika/`.

## Apply Points

Apply cluster infrastructure from omega:

```bash
kubectl apply -f deploy/vultr/paprika/omega-gateway.yaml
kubectl apply -f deploy/vultr/paprika/omega-referencegrant.yaml
kubectl apply -f deploy/vultr/paprika/omega-tls.yaml
```

Apply workload registrations from each app repo:

```bash
kubectl apply -f ~/projects/brandbrain/deploy/kubernetes/paprika/application.yaml
kubectl apply -f ~/projects/cuttlefish/deploy/kubernetes/paprika/application.yaml
kubectl apply -f ~/projects/flaggr/deploy/kubernetes/paprika/application.yaml
kubectl apply -f ~/projects/uptime/deploy/kubernetes/paprika/application.yaml
```

## Operational Notes

- Do not set image tags in Paprika `Application` parameters unless intentionally overriding a release.
- Do not put workload charts or live cluster app manifests back into the Paprika repo.
- Keep cluster memory/session notes under `docs/paprika/sessions/`.
- Use `[skip ci]` on automated chart bump commits to avoid recursive app repo deploys.
