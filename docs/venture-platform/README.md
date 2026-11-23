# Omega venture platform programme

This directory imports the Dropshippr → Omega feature programme into `castlemilk/omega`. It is an additive product programme, not a replacement of the repository's existing orchestration/infrastructure implementation.

The reviewed backlog comprises **96 feature specifications in 12 epics**, connected to **64 Dropshippr workflows, 27 proposed Omega workflows and 32 UI screen families**. Feature implementation remains Proposed; concepts, local prototype behaviour and production acceptance are different evidence.

- [GitHub programme tracker #8](https://github.com/castlemilk/omega/issues/8)
- [Verified import report and feature issue index](IMPORT-REPORT.md)
- [Machine-readable issue mapping](issue-map.json)
- [UI screen coverage and complete journey routes](ui-coverage.md)
- [Screenshot previews and provenance](screenshots/README.md)
- [Design and component implementation contract](design-contract.md)

`IMPORT-REPORT.md` and `issue-map.json` are produced only after the importer verifies the issue set. Their presence, rather than an unverified planned count, establishes the GitHub import result.

## Feature specifications

| Epic | Stable IDs | Specification |
|---|---|---|
| E01 Strategy and transition | OME-001–008 | [Strategy](backlog/e01-strategy.md) |
| E02 Design foundations | OME-009–016 | [Design foundations](backlog/e02-design.md) |
| E03 Operational components | OME-017–024 | [Components](backlog/e03-components.md) |
| E04 Navigation and journeys | OME-025–032 | [Journeys](backlog/e04-journeys.md) |
| E05 Domain, tenancy and migration | OME-033–040 | [Domain](backlog/e05-domain.md) |
| E06 Discovery and validation | OME-041–048 | [Discovery](backlog/e06-discovery.md) |
| E07 Agent authority | OME-049–056 | [Authority](backlog/e07-authority.md) |
| E08 Durable workflows | OME-057–064 | [Workflows](backlog/e08-workflows.md) |
| E09 Brand and product production | OME-065–072 | [Production](backlog/e09-production.md) |
| E10 Commerce and operations | OME-073–080 | [Commerce](backlog/e10-commerce.md) |
| E11 Economics and portfolio learning | OME-081–088 | [Economics](backlog/e11-economics.md) |
| E12 Integrations, quality and rollout | OME-089–096 | [Release](backlog/e12-release.md) |

Each specification carries the original priority, responsible discipline, relative size, dependencies, acceptance evidence, screen binding and additional UI acceptance. Disciplines are not personal assignments and relative sizes are not delivery dates.

## Product and design direction

The platform discovers opportunities, validates demand, prepares ventures, produces and reviews products, supervises bounded operations and learns from measured outcomes. Its first proof remains the existing digital-product workflow.

Use original industrial precision with desert-modernist warmth: mineral black, warm charcoal, pale sand and restrained copper/amber. Keep cinematic imagery on orientation surfaces, away from forms, tables and approval payloads. **Terraform** is explained as **Prepare a venture**. Scout, Frontiers, Validate, Deploy, Operate, Expand and Sustain can supplement explicit task language. Do not use Colonise/Collanise in active copy.

Business → Product → Product pipeline, Business → Project → Content and the proposed Organisation → Portfolio → Venture hierarchy are not silently interchangeable. Their writable mapping requires OME-001/034. Preserve Technical Posters, Signal Studies, Finishline Editions and Birthday Cards identities, originals, versions and review evidence. Polsia is a competitor benchmark, not an owned venture.

## Delivery gates

1. **A: Design agreement.** Task-specific direction, tokens, navigation and operational screens.
2. **B: Read-only shell.** Existing data and ownership preserved; desktop/mobile, keyboard and recovery acceptance.
3. **C: Supervised pilot.** Exact artwork and Copy versions through an internal digital-product review packet.
4. **D: One external action.** Exact approval, scoped credentials, budget reservation where applicable, idempotency/reconciliation, receipts, pause and hosted acceptance.
5. **E: Bounded operation.** Expand only from measured outcomes and completed controls.

Sequence: foundations and scope → content/recipes/copy/review → discovery/Terraform → approvals/runtime → connected commerce/economics → additional customer branches. Physical fulfilment and logo commissions remain later work. A prepared recipe is not generated output; a metadata packet is not a customer file; approval is not confirmed external execution.

## Source documents and original assets

- [Programme and source backlog](https://chatgpt.com/space/page_9ef91fb792d08191a6e9f4070395992e)
- [Full workflow and journey inventory](https://chatgpt.com/space/page_d93193af8304819193b45a81d9bd9223)
- [32-screen UI atlas and interactive HTML prototype](https://chatgpt.com/space/page_bc328f44577081918e32b04b4daa5d61)
- [Design system and artistic direction](https://chatgpt.com/space/page_944f9c94f3488191b65501f21dc03384)
- [Domain model and journey contracts](https://chatgpt.com/space/page_e9b5dd9d172881918d3a056a36f3717a)
- [20 original image concepts, contact sheet, five image packs and manifests](https://chatgpt.com/space/page_8242867176f48191938ce84c887d3f31)

Space references keep their existing permissions. The native specification files are included here so issue acceptance does not depend on access to Space. The complete interactive HTML and full-resolution original-image packs remain in Space; this import does not claim to have copied those binaries into GitHub.

## Import verification

`tools/import_backlog.py --dry-run` validates exactly 96 features, 12 epics, complete required fields and an acyclic dependency graph. The write mode is restricted to this repository and the reviewed import branch, reuses stable markers and stops on unresolved create outcomes. It does not close issues or change assignees. Existing unrelated issues remain untouched.

Generated concept values do not establish revenue, venture ownership, health or running agents. UI browser behaviour, responsive layout and accessibility remain separate acceptance work in OME-015, OME-032 and OME-093. No application deployment or external business action is performed by importing documentation.
