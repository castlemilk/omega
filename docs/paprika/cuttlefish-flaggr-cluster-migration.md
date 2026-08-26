# Cuttlefish And Flaggr Cluster Migration

Status: superseded by app-owned GitOps.

Cuttlefish and Flaggr now own their Kubernetes charts and Paprika `Application` manifests in their source repos:

- Cuttlefish chart: `~/projects/cuttlefish/deploy/kubernetes/chart`
- Cuttlefish Application: `~/projects/cuttlefish/deploy/kubernetes/paprika/application.yaml`
- Flaggr chart: `~/projects/flaggr/deploy/kubernetes/chart`
- Flaggr Application: `~/projects/flaggr/deploy/kubernetes/paprika/application.yaml`

Their deploy workflows build images, bump in-repo chart values, commit with `[skip ci]`, and let Paprika sync from each app repo.

See `docs/paprika/vke-gitops-apps.md` for the current release flow.
