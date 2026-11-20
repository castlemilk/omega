# Business Studio

Business Studio is the private operator console for the venture pilot. Both Omega runtime dashboards open its **Command** view. Operators can follow a review to its product or open a saved workflow run at its current checkpoint. Studio resolves the signed-in owner and reads that owner's saved workspace.

## Connect a dashboard

Set `OMEGA_BUSINESS_STUDIO_ORIGIN` to the HTTPS origin of the private Studio installation that serves `/command`. Export it before `omega run` or either Vite build. With Docker Compose, set it in the root `.env` before starting the dashboard. For example, a test installation at `https://studio.example.org` opens `https://studio.example.org/command`.

In either dashboard, choose **Business Studio** in the sidebar. The link opens in the same tab. With an active Studio session, browser Back returns to the runtime page. A blank setting leaves the entry hidden. A malformed setting stops the dashboard build with the name of the setting.

## Ownership and vocabulary

| Term | Meaning in the pilot |
| --- | --- |
| Workspace | One operator's collection of saved businesses and products. Studio authenticates the owner. |
| Portfolio | The Command view across the owner's businesses. Choosing a business narrows its review queue. |
| Business | The existing parent record for products. Keep its source identity through the pilot. |
| Product | A deliverable owned by one business. A business can have several products. |
| Project | In Studio, the working view for a specific business and product. In the Omega runtime, a project groups orchestration nodes. An operator entering Studio selects business scope there. |
| Venture | The proposed operating unit for a thesis, mandates, brands and products. Mapping a saved business to a venture requires a recorded decision. |
| Brand, channel and legal entity | A market identity, a distribution destination and a legal owner respectively. An existing poster or card collection keeps its identity until its commercial relationship is verified. |
| Workflow and agent | A workflow defines the steps. An agent can execute steps within a mandate. Reviewing a saved run leaves its authority and revision intact. |

**Terraform** means **Prepare a venture**. A draft or a parent–child venture relationship alone conveys no budget, credentials or permission to act. Technical Posters, Signal Studies, Finishline Editions and Birthday Cards retain their source identities. Commercial ownership and writable venture conversion remain open decisions. [Product vocabulary](https://github.com/castlemilk/omega/issues/10) · [Ownership contracts](https://github.com/castlemilk/omega/issues/32)

## Entry and recovery

| Operator action | Expected result |
| --- | --- |
| Open Business Studio from a runtime project | Open the private portfolio at `/command`. The handoff carries no runtime project, credentials, query string or referrer. |
| Follow a saved run while signed out | After owner sign-in, restore the requested business, queue, page, cursor and run when present. |
| Open the product associated with a run | Display the saved product within its business. Existing product and catalogue bookmarks continue to work. |
| Request a run under another business | Show the unavailable state. The scoped list and detail reads use the current owner's workspace. |

The dashboard regression test runs on two local servers and intercepts the outbound navigation at a synthetic Studio origin. Install the locked dependencies in both dashboard directories, install Chromium with `npx playwright install chromium` in `web/dashboard`, and run `npm run test:e2e:studio` there. The private Studio checkout owns the combined browser test with the compiled Worker, local D1 records and a synthetic identity provider.

The next pilot milestone is a supervised digital-product review with exact artwork and copy versions, separate scientific, editorial and print assessments, and an evidence packet. Connecting the console advances the scoped navigation and journey tickets. Hosted sign-in, release verification and the review packet have their own acceptance criteria. [Scoped shell](https://github.com/castlemilk/omega/issues/55) · [Journey validation](https://github.com/castlemilk/omega/issues/75) · [Launch readiness packet](https://github.com/castlemilk/omega/issues/100)
