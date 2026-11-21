# Business Studio

Business Studio is the private operator console for the venture pilot. Both Omega runtime dashboards open its **Command** view. Operators can follow a review to its product or open a saved workflow run at its current checkpoint. Studio resolves the signed-in owner and reads that owner's saved workspace.

## Connect a dashboard

Set `OMEGA_BUSINESS_STUDIO_ORIGIN` to the HTTPS origin of the private Studio installation that serves `/command`. Export it before `omega run` or either Vite build. With Docker Compose, set it in the root `.env` before starting the dashboard. For example, a test installation at `https://studio.example.org` opens `https://studio.example.org/command`.

In either dashboard, choose **Business Studio** in the desktop sidebar or in the top bar on a phone. The mobile menu opens the other dashboard routes. The link opens in the same tab. With an active Studio session, browser Back returns to the runtime page. A blank setting leaves the entry hidden. A malformed setting stops the dashboard build with the name of the setting.

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

## First operating business

Omega is being built to operate a business from an owner's goal and budget. It should prepare the work, ask for decisions the owner reserved, carry out an approved action once, and select the next experiment from observed results. The first business is digital posters. Signal Studies is its first three-print edition.

Run `omega posters prepare /path/to/studio/public/collections/signal-studies` to reproduce the release candidate from the original files. The command checks the delivery ZIP, original launch kit, review PDF and A4 proof. It identifies the six printable files, printing instructions, font notice and the exact listing text. The candidate uses the shared protobuf contract. Studio checks it against its own archives as part of local release validation.

Studio's scheduled poster operation pairs the immutable artwork and copy revisions and presents the packet in the private console. Approval is bound to its digest and the private demo destination. A hold pauses release. The demo can record five distinct consenting readers' choices and whether they understood digital delivery. The resulting counts determine whether the next proposal concerns delivery wording, lead artwork or a measured channel test. A private reader screen supplies qualitative evidence. Sales, costs, refunds and order fulfilment require their own channel receipts.

The switching test for the first store is two consecutive cycles inside the owner's mandate, with evidence of the executed action, the result, spend and operator effort for each. Public sales, buyer delivery and support must be demonstrated on the selected channel before handing Omega those responsibilities. [Poster pilot](https://github.com/castlemilk/omega/issues/28) · [Authorised publication](https://github.com/castlemilk/omega/issues/106) · [Operating outcomes](https://github.com/castlemilk/omega/issues/103)

## Measure the poster channel

After an approved channel test, use the `metrics-template.csv` from the Signal Studies development kit. The report selects one experiment, one exact listing-specific measurement URL and an inclusive window of complete UTC days. The source URL identifies the supplied export. The report retains the file digest so the operator can reconcile it with the original.

```sh
omega posters measure observations.csv \
  --experiment "$POSTER_EXPERIMENT" --source "$POSTER_MEASUREMENT_URL" \
  --from "$FIRST_UTC_DAY" --through "$LAST_UTC_DAY" --evidence reported
```

For a daily row, set `period_start` and `period_end` to the same YYYY-MM-DD date. Use an RFC 3339 `observed_at` from after the reporting day closed. Record `impressions`, `clicks`, `listing_visits`, `orders` and `refunds` as whole counts with unit `count`. For `gross_revenue`, `fees` and `ad_spend`, use decimal amounts with unit `currency` and the three-letter currency code. Refunds here count reported refunds. Record an observed zero as `0` and leave an unknown value empty. Identical daily observations count once. Conflicting values for the same day, metric and currency require reconciliation against the source.

Omega computes a total only when that series covers every requested day. It reports each currency separately. Click-through uses clicks divided by impressions. Order conversion uses orders divided by listing visits. Missing inputs or a zero denominator leave the rate empty. At least 14 complete days and 100 relevant listing visits make the evidence eligible for an owner review. These thresholds come from the original launch plan and carry no claim about demand or profit. Use `--evidence simulated` for a rehearsal. Simulated reports always have a separate verdict.
