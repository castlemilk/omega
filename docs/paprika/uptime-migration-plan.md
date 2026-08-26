# Uptime / Telesis Migration Plan

Status: superseded by app-owned GitOps.

Uptime now carries the Telesis stack chart and Paprika `Application` manifest directly:

- Chart: `~/projects/uptime/deploy/kubernetes/chart`
- Application: `~/projects/uptime/deploy/kubernetes/paprika/application.yaml`

The current target is one Paprika app, `telesis-api`, tracking all Telesis components through a single chart render and release history.

See `docs/paprika/vke-gitops-apps.md` for the current release flow and validation entry points.
