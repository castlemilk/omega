# Omega UI and workflow coverage

Source: [UI atlas and prototype](https://chatgpt.com/space/page_bc328f44577081918e32b04b4daa5d61) and [workflow inventory](https://chatgpt.com/space/page_d93193af8304819193b45a81d9bd9223).

This is design coverage, not implementation completion. DS01–DS64 and O01–O27 are workflow identifiers; S01–S32 are screen families. They extend the existing OME-001–096 specifications rather than create duplicate feature identities. DS62, mobile and assistive-input completion, applies throughout.

## Screen contracts

| Screen | Primary task and required action | Workflow coverage |
|---|---|---|
| S01 Entry and onboarding | Find an opportunity / Develop an idea / Bring an existing business; Continue to brief; preserve draft and required-field errors. | DS01, DS55, O01 |
| S02 Business setup and import | Read-only source inventory and explicit Product/Project mapping; Save mapping draft; preserve duplicates, partial imports and source identities. | DS02, DS03, DS05, O04, O26 |
| S03 Command and scoped registry | Needs your review before registry; show record type, scope, stage, decision and freshness; open exact workspace or exception. | DS04, DS06, O05, O07, O08 |
| S04 Frontiers | Compare industry/customer-segment hypotheses with source coverage and contradictions; Open validation brief. | DS07, DS09, O02, O08 |
| S05 Evidence and validation | Hypothesis, versioned protocol, evidence ledger and decision; Save experiment draft; insufficient evidence is explicit. | DS08, DS42, DS47, O03 |
| S06 Terraform formation | Prepare a venture through Thesis → Blueprint → Resources → Review; Create draft venture; credentials/customers are not inherited. | O05, O06 |
| S07 Product pipeline | Actual preparation phases, artifacts and decisions; Record phase decision with evidence; changing stage is not publication. | DS10, DS59 |
| S08 Project content and catalogue | Separate project assets from shared catalogue; Add selected reference to project; loaded-only coverage and missing previews stay honest. | DS11, DS12, DS13, DS14 |
| S09 Artwork and recipe | Dominant artwork preview, Source/Recipe/Versions inspector; Save child recipe or Prepare batch; recipe is Not generated until actual output exists. | DS15, DS17, DS18, DS19, DS20, DS21, DS61 |
| S10 Brand kit | Identity, typography, voice and asset references with pinned inheritance/overrides; Save brand version; preserve child-brand identity. | DS05, DS16 |
| S11 Variant review | Exact A/B versions at consistent scale; Request changes or Approve editorial review; scientific, rights and print checks remain independent. | DS22, DS26, DS27 |
| S12 Copy studio | Project-linked editor and exact save receipts; Save version; unknown outcome retains draft and offers Check saved revision. | DS23, DS56, DS57 |
| S13 Technical Posters composition | Separate customer brand; artwork/title/equation/annotation layers, numeric controls, Undo/Redo; Review output; unavailable 3D is explicit. | DS24, DS25 |
| S14 Output preflight | Source/Output/Checks with real file facts; Export planning report; preview is not print master; final render remains disabled when held. | DS28, DS31, DS32 |
| S15 Review packet and manifest | Exact artwork/Copy and file role/version/checksum inventory; Export review packet; metadata packet differs from customer package; read-only bounded import. | DS29, DS30, DS33, DS34, DS58 |
| S16 Offer and listing | General offer / channel draft / own store fields, asset tray and preview; Prepare offline listing pack; unresolved rights/price/delivery remain visible. | DS35, DS36, DS37 |
| S17 Exact-action approval | Destination/account, versioned payload diff, ceiling and expiry; Approve this version, Request revision or Reject; approval is not execution. | DS38, DS39, DS40, O12 |
| S18 Experiments and growth | Organic pilot and optional paid draft; protocol, observations, caps and stop rules; Save experiment version or Request campaign approval. | DS41, DS42, DS43, DS44, DS45, DS47, O21 |
| S19 Capital and contribution | Authorised/reserved/settled/available funds and source-linked ledger; Review allocation proposal; actuals differ from scenarios. | DS46, O13, O22 |
| S20 Business CRM and support | Inbox → conversation → order/context; Save reply draft with separate send authority; purpose/brand/channel consent and human takeover. | DS48, DS49, O19, O20 |
| S21 Customer purchase and access | Separate customer identity; checkout, pending confirmation, confirmed entitlement, failure/expiry/refund/dispute; only confirmed access enables files. | DS50, DS51, DS52, DS53 |
| S22 Physical operations | Deferred qualification and separate orders; Record qualification evidence; payment, production approval, supplier acceptance/billing and shipment differ. | DS54, deferred physical branch |
| S23 Agents and mandates | Registry plus Definition/Mandate/Tools/Evaluations; Save mandate draft; exact scope, cost, deadline and delegation limits. | O09, O10, O18 |
| S24 Workflow authoring | Typed canvas and equivalent step list; Validate workflow / Save version; approvals and repair branches explicit; simulation never publishes. | DS59, O14, O16 |
| S25 Run inspection | Mandate/version, events, receipts, artifacts and cost; Open decision or Reconcile outcome; pause accessible, cancel is not reversal. | O15, O16, O17, O18 |
| S26 Integrations and MCP | Verified account, mode, capabilities, health and receipts; Review capability grant; no exposed secrets or installation-implied authority. | DS60, O11, O25 |
| S27 Recovery and release evidence | Retained draft versus persisted revision, uncertain effects and release holds; Reconcile selected operation; local tests differ from hosted/deployment evidence. | DS57, DS58, DS61, DS63, DS64, O18, O27 |
| S28 Blueprint library | Versioned playbooks/lessons with origin, evidence, applicability and sharing scope; Use this version in a draft; no copied credentials/customers. | O23 |
| S29 Access privacy and usage | Scoped access, privacy, exports and platform billing; Review access change / Prepare permitted export / Review plan change; impact review before mutation. | O24, O26 |
| S30 Finishline Editions | Separate customer brand; Race → Details → Review; preserve city/details; Review personal edition; no invented rights, route verification or availability. | Race-edition customer journey |
| S31 Birthday Cards | Nature-led separate brand; bounded personalisation; Front/Inside/Back/Unfolded; Review complete card with visible overflow and output/fold gates. | Card customer journey |
| S32 Logo commissions | Deferred service branch; Brief → concepts/revisions → Review → Package; Send revision notes; explicit scope, rights and unresolved checks. | Made-to-order customer journey |

## Complete journey routes

| Journey | Screen route | Outcome |
|---|---|---|
| J01 Establish business/product | S01 → S02 → S03 → S07 | Correct scope and independent product history. |
| J02 Idea to shortlist | S04 → S05 → S07 | Evidence-led shortlist, defer or reject. |
| J03 Inspiration to content | S08 → S09 → S11 → S15 | Traceable project-owned content, honest generation status. |
| J04 Product review | S09 → S12 → S11 → S15 → S17 where required | Version-bound review, not blanket publication authority. |
| J05 Prepare and publish | S14 → S15 → S16 → S17 | Offline pack or separately approved/reconciled publication. |
| J06 Market learning | S18 → S19 → S05 → S07 | Preserved experiment outcome and next decision. |
| J07 Recover interrupted work | Origin → S27 → origin | Retained draft/state without silent loss or duplicate effects. |
| J08 Factory-to-storefront | S15 → S16 → S17 → S21 | Controlled handoff and later verified customer access. |
| Omega opportunity discovery | S01 → S04 → S05 → S06 | Continue, pivot, pause, stop or inconclusive with evidence. |
| Omega existing-business import | S01 → S02 → S03 → S26 | Explicit mapping, preserved identities and known gaps. |
| Omega digital-product build | S06 → S10 → S08 → S09 → S11 → S14 → S15 → S16 → S17 | Reviewed candidate or confirmed external publication, distinguished. |
| Omega portfolio supervision | S03 → S17 → S25 → S19 | Durable decisions and owned unresolved work. |
| Omega related-venture spawning | S03 → S28 → S06 → S23 | Independent draft with traceable lineage. |
| Omega intervention or closure | S25 → S27 → S29 | Verified recovery or retained obligations and owner. |
| Technical Posters customer | S13 → S14 → S21 | Layered composition, qualified output and customer access. |
| Finishline customer | S30 → S21 | Preserved race personalisation and reviewed deliverable. |
| Birthday Cards customer | S31 → S14 → S21 | Complete card review and verified output. |
| Logo commission customer | S32 → S21 | Scoped revisions, accepted package and shared commerce if enabled. |
| Physical product qualification | S22 | Deferred, provider and output evidence required. |

## Cross-cutting state acceptance

Distinguish first use, no results, missing permission, disconnected source, loading, partial coverage, stale evidence, missing preview/original, ungenerated recipe, dirty/saving/saved, conflict, unknown outcome, cancellation and unsupported capability. Retain drafts and selection, explain the next safe action, support keyboard/touch and restore focus. Relevant tables require restorable filters, typed sorting and explicit pagination/load scope.

The desktop reference is 1536 × 1024 with a 390px narrow-layout contract. Also test short-height screens, 200% text zoom and reduced motion. Shared data and state must drive both graph/list and edit/preview modes. A screenshot alone does not prove interaction or accessibility.

## Prototype boundary

The source atlas attaches a 32-screen self-contained HTML prototype with in-session forms, filters, navigation and illustrative state controls. It is not connected to APIs, payments, publication, customers, suppliers or real agents. Session state resets on reload. The source records syntax/template/modelled-state validation only; prior browser access was blocked. Actual browser behaviour and fidelity remain open acceptance work. This GitHub document does not claim to package or validate the HTML attachment.
