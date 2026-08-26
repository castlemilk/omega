# BrandBrain API Cluster Migration

Status: superseded by app-owned GitOps.

BrandBrain now owns its Kubernetes chart and Paprika `Application` in the source repo:

- Chart: `~/projects/brandbrain/deploy/kubernetes/chart`
- Application: `~/projects/brandbrain/deploy/kubernetes/paprika/application.yaml`
- Source: `https://github.com/skunkworq/brandbrain.git`

The deploy workflow builds the BrandBrain API image, bumps `deploy/kubernetes/chart/values.yaml`, commits the chart bump with `[skip ci]`, and Paprika syncs from `deploy/kubernetes/chart`.

See `docs/paprika/vke-gitops-apps.md` for the current release flow.
