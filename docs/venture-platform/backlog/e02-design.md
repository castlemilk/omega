# E02 Design foundations

Source: https://chatgpt.com/space/page_ecfb1fb37cec8191bfb9426190b56f82

All tickets are Proposed. Foundry is the dark operator treatment, Institute its light counterpart, and Deep Field a restrained expressive treatment for orientation/marketing. The latest selected direction is mineral black, warm charcoal, sand and restrained copper/amber. Exploration is not screen-level acceptance. Use one component grammar and preserve separate customer brands.

## OME-009 Establish the artistic direction and visual acceptance rubric

**P0 · Brand design · M · Dependencies: OME-001, OME-006**

Define the industrial-futurist concept through material, composition, type, imagery and motion. Produce readable system and full-screen concepts, including a narrow state.

**Acceptance:** compare Foundry, Institute and Deep Field on the same task; use original marks and real product terminology; show calm and approval states; score hierarchy, legibility, distinctiveness, implementation feasibility and data honesty; capture an explicit direction decision.

**Screens:** S01, S03, S05, S17.

**UI acceptance:** reserve Deep Field scenery for orientation; carry the latest warm palette into operational screens without fortress heroes behind forms. Record direction selection separately from screen acceptance.

**Evidence:** concept boards and annotated rubric. Avoid decorative cockpit graphics throughout the application.

## OME-010 Build the semantic token contract

**P0 · Design systems and frontend · M · Dependencies: OME-009**

Specify primitive, semantic and component tokens for themes, spacing, type, geometry, focus, elevation, motion and chart series.

**Acceptance:** components consume semantic roles rather than raw colours; success, warning, danger and selection are distinguishable without colour alone; machine-readable tokens and CSS share a version; contrast checks cover normal, hover, focus and disabled states; deprecated tokens have migration aliases.

**Screens:** all shared components.

**UI acceptance:** publish one versioned runtime source for surfaces, text, accent, status, focus, border, spacing and motion. Keep customer-brand themes distinct. Verify warning and uncertain states in both operator treatments.

**Evidence:** token schema, fixtures and contrast report. Palette contrast alone is not whole-interface accessibility certification.

## OME-011 Define typography and operational density

**P0 · Design systems · S · Dependencies: OME-009**

Use disciplined sans-serif controls/prose, restrained extended identity lettering and monospace for identifiers/telemetry. Offer comfortable and compact density without shrinking critical text.

**Acceptance:** body, controls, tables, labels and numbers have explicit size, line-height and weight; tabular numerals align economics; long names and localised values do not collide; fallbacks preserve layout; 200% text zoom remains usable.

**Screens:** S05, S08, S12, S19, S25.

**UI acceptance:** provide prose, dense-table and log specimens; test long names, amounts and short viewports. Do not use tiny tracked capitals for essential instructions.

**Evidence:** type specimens and dense-table examples. No font binaries are included in this import.

## OME-012 Develop an original mark and icon family

**P1 · Brand design · M · Dependencies: OME-009**

Explore an interrupted enclosure, axial gate or folded industrial form, not a franchise insignia or watch-brand treatment.

**Acceptance:** mark works in monochrome and at favicon size; wordmark spacing/minimum sizes are specified; icons use consistent geometry and accessible labels; selection does not depend on glow; brand artwork and operational status icons remain separate.

**Screens:** shared navigation and action icon family.

**UI acceptance:** construct original vector marks and a 24px family: Scout beacon, Terraform strata, Deploy outbound arrow, Workflows nodes and Agents segmented geometry. Include monochrome, selected, small-size and accessible-name examples; raster concepts are not a completed SVG library.

**Evidence:** construction notes, lockups and small-size tests. Public adoption also depends on OME-002.

## OME-013 Specify motion and spatial transitions

**P1 · Motion design and frontend · M · Dependencies: OME-009, OME-010**

Define short state transitions, drawer movement, run-progress updates and optional assembled-to-exploded brand animation for expressive surfaces.

**Acceptance:** motion never implies unobserved execution; reduced motion removes spatial travel/loops; inactive tabs suspend decoration; interruption leaves controls responsive; stable non-WebGL fallback exists; timings are measured in the browser.

**Screens:** S01, S06, S09, S24, S25.

**UI acceptance:** specify entry, drawer, state-change and graph transitions; provide static/reduced-motion alternatives and preserve controls during interruption.

**Evidence:** motion matrix, state diagrams and performance trace. Excludes permanent scanlines, blinking decoration and mandatory operator-screen 3D.

## OME-014 Implement accessibility and input conventions

**P0 · Accessibility and frontend · M · Dependencies: OME-010, OME-011**

Target WCAG 2.2 AA for complete workflows, with stronger internal touch/focus conventions where practical. Reference: https://www.w3.org/TR/WCAG22/

**Acceptance:** test keyboard paths, focus return, screen-reader names and error association; normal text meets 4.5:1 and meaningful UI graphics 3:1 where applicable; dragging has a non-drag alternative; sticky chrome does not hide focus; verify minimum targets and exceptions, preferring 44px for primary touch actions.

**Screens:** every complete journey.

**UI acceptance:** verify touch-visible controls, non-drag editing, 200% zoom, 390px, desktop and short-height layouts. Record measurements rather than infer accessibility from screenshots.

**Evidence:** automated checks plus manual keyboard and assistive-technology review.

## OME-015 Establish the component catalogue and visual regression harness

**P0 · Design systems and quality · M · Dependencies: OME-010, OME-011, OME-014**

Create isolated stories and representative screens using existing frontend conventions. Review shadcn/Gamma compatibility before adoption; do not default to a parallel UI stack.

**Acceptance:** components have interaction/state examples; screenshots cover approved viewport/theme/density combinations; fixtures are labelled; visual changes require reviewed diffs; releases identify component/token versions.

**Screens:** component and state catalogue; S03 and S08 first.

**UI acceptance:** stories cover scope bars, evidence inspectors, version strips, artifact roles, decision gates, mandates, receipts, recovery panels, ledgers and workflow nodes. Add screen/state visual regressions.

**Evidence:** runnable catalogue, visual baselines and contributor guide. Snapshot success does not replace task-based review.

## OME-016 Define imagery and editorial asset rules

**P1 · Art direction and content design · M · Dependencies: OME-009, OME-012**

Define original architectural renders, cutaways, specimen photography, macro materials and product-art presentation. Keep cinematic imagery outside critical controls.

**Acceptance:** manifests retain source, generation method, rights notes and crop; thumbnails preserve identity; themes never tint product originals; web previews and customer files are distinct; social/onboarding/empty imagery share a family.

**Screens:** illustration and asset package, with S01 orientation and restrained S04/S06 motifs.

**UI acceptance:** retain exact source files/provenance; record surface, crop, theme and decorative/product role. Extract standalone assets only where source quality permits. Generated metrics, competitor identities and mock originals must not become live data.

**Evidence:** art-direction library and briefs for hero, onboarding, empty, error and documentation surfaces. Excludes treating third-party promotional imagery as owned artwork.
