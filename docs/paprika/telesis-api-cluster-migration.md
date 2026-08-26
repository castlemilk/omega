# Telesis API Cluster Migration

Status: superseded by app-owned GitOps.

Telesis is managed from the `uptime` source repo as one Paprika app covering the API, scheduler, runner, result processor, and rollup components:

- Chart: `~/projects/uptime/deploy/kubernetes/chart`
- Application: `~/projects/uptime/deploy/kubernetes/paprika/application.yaml`
- Source: `https://github.com/skunkworq/uptime.git`

The deploy workflow builds the full image set, bumps all image tags in `deploy/kubernetes/chart/values.yaml`, commits with `[skip ci]`, and Paprika syncs the stack from the app repo.

See `docs/paprika/vke-gitops-apps.md` for the current release flow.
