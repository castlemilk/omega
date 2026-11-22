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

To verify the corrected edition, run `omega posters prepare --edition signal-studies-editorial-01 "$SIGNAL_STUDIES_COLLECTION"`. It selects the Phase portrait A4 artwork, checks the corrected six-PDF ZIP and review PDF and reads the saved listing title and its three paragraphs from `reader-proof-01/listing.txt`. The original edition remains available as `signal-studies-v0.1` and is the default for `prepare`.

For the Wave field caption revision, save the buyer ZIP and the three-page edition preview from Studio in one directory, using their supplied names `signal-studies.zip` and `edition-preview.pdf`. Omega checks those exports against the signed-in review and the original collection. The same `--caption-files` option is available on the isolated test checkout. An existing order downloads the ZIP recorded at purchase.

```sh
omega posters prepare "$SIGNAL_STUDIES_COLLECTION" \
  --edition signal-studies-caption-01 --caption-files "$CAPTION_DOWNLOADS"
```

Studio's scheduled poster operation pairs the immutable artwork and copy revisions and presents the packet in the private console. Approval is bound to its digest and the private demo destination. A hold pauses release. The demo can record five distinct consenting readers' choices and whether they understood digital delivery. The resulting counts determine whether the next proposal concerns delivery wording, lead artwork or a measured channel test. A private reader screen supplies qualitative evidence. Sales, costs, refunds and order fulfilment require their own channel receipts.

The switching test for the first store is two consecutive cycles inside the owner's mandate, with evidence of the executed action, the result, spend and operator effort for each. Public sales, buyer delivery and support must be demonstrated on the selected channel before handing Omega those responsibilities. [Poster pilot](https://github.com/castlemilk/omega/issues/28) · [Authorised publication](https://github.com/castlemilk/omega/issues/106) · [Operating outcomes](https://github.com/castlemilk/omega/issues/103)

### Verify a seller download

Open **Walkthrough → Seller draft** in Studio. Choose the issued edition or its proposal, download the seller ZIP, and copy that download link. From the same edition’s review, save the review packet. Omega checks both local files against the packet and draft identified by the link.

```sh
omega posters verify-seller "$SELLER_ZIP" "$REVIEW_PACKET" --from "$STUDIO_DOWNLOAD_URL"
```

On success the command writes Studio’s verified seller manifest to standard output. It checks the four listing photos and their source sheets, the listing text, seller notes, observation template and every file inside the buyer ZIP. The manifest records whether the materials describe a proposal or an issued edition. A mismatch exits with an error before output. The check runs offline.

## Measure the poster channel

After an approved channel test, use the `metrics-template.csv` from the Signal Studies development kit. The report selects one experiment, one exact listing-specific measurement URL and an inclusive window of complete UTC days. The source URL identifies the supplied export. The report retains the file digest so the operator can reconcile it with the original.

```sh
omega posters measure observations.csv \
  --experiment "$POSTER_EXPERIMENT" --source "$POSTER_MEASUREMENT_URL" \
  --from "$FIRST_UTC_DAY" --through "$LAST_UTC_DAY" --evidence reported
```

For a daily row, set `period_start` and `period_end` to the same YYYY-MM-DD date. Use an RFC 3339 `observed_at` from after the reporting day closed. Record `impressions`, `clicks`, `listing_visits`, `orders` and `refunds` as whole counts with unit `count`. For `gross_revenue`, `fees` and `ad_spend`, use decimal amounts with unit `currency` and the three-letter currency code. Refunds here count reported refunds. Record an observed zero as `0` and leave an unknown value empty. Identical daily observations count once. Conflicting values for the same day, metric and currency require reconciliation against the source.

Omega computes a total only when that series covers every requested day. It reports each currency separately. Click-through uses clicks divided by impressions. Order conversion uses orders divided by listing visits. Missing inputs or a zero denominator leave the rate empty. At least 14 complete days and 100 relevant listing visits make the evidence eligible for an owner review. These thresholds come from the original launch plan and carry no claim about demand or profit. Use `--evidence simulated` for a rehearsal. Simulated reports always have a separate verdict.

## Rehearse a poster purchase and refund

The owner can run either reviewed Signal Studies edition through a separate Stripe sandbox. The private Studio listing supplies the reviewed artwork and exact archive. Use the exported review packet and its SHA-256 from the private listing receipt. The packet selects the edition for checkout. A buyer of the original edition receives `signal-studies-print-candidate.zip`. A buyer of the corrected edition receives `signal-studies.zip`. Each order keeps its original packet and files when the checkout switches editions. The sandbox offer charges A$12 in simulated funds and grants a 24-hour test download. The hosted store has its own checkout setting.

Configure `OMEGA_POSTER_COMMERCE_DATABASE_URL` for a dedicated local PostgreSQL database and `OMEGA_POSTER_STRIPE_TEST_KEY` for the selected sandbox. Start the Stripe CLI listener in that same sandbox, forwarding to `http://127.0.0.1:9746/stripe/events`. Subscribe to Checkout completion, asynchronous success/failure and expiration, payment intent failure, charge success/failure/refund, dispute created/updated/closed, and refund created/updated/failed. Set `OMEGA_POSTER_STRIPE_SIGNING_SECRET` to the listener's signing secret.

```sh
omega posters test-checkout "$SIGNAL_STUDIES_COLLECTION" \
  --packet "$APPROVED_PACKET" --packet-sha256 "$APPROVED_PACKET_SHA256"
```

Open the printed loopback address, start checkout and use Stripe's published test buyer details. On return, the order page displays the provider-confirmed state. A declined buyer can resume the same open checkout or cancel it. A paid buyer can download their edition’s six PDFs, printing guide and font notice. The same browser profile retains its private order access across restarts. The operator can refund the test charge in the same Stripe sandbox. A full refund closes future downloads, including requests from an already-open payment confirmation page. Partial refunds retain access. An open or lost dispute suspends downloads. Returned files already saved on a device stay there. [Stripe testing](https://docs.stripe.com/testing)

`omega posters test-order-receipt ORDER_ID` checks the current provider state and exports the operator's receipt. It includes the edition, file checksum, test price, payment and refund state, number of downloads, entitlement and signed event processing. The reader requires the order database and the same sandbox account. Keep the receipt with the private pilot evidence. Reporting customer demand or revenue requires production observations.

`make test-digital-orders` starts a fresh local PostgreSQL container, runs the race-enabled order, signature and reconciliation tests, and drives Chromium through purchase, download and revocation with a local provider fixture. It uses Docker, Node and the locked Playwright installation in `web/dashboard`. The local commit hook runs this suite for changes to the poster order flow.

Set `OMEGA_POSTER_TEST_COLLECTION` to Studio’s `public/collections/signal-studies` directory when running those tests to include both reviewed editions. The test buys each edition through the local provider, switches to the corrected checkout, then verifies each order’s original download and receipt. Chromium also opens the Phase portrait preview, downloads the corrected ZIP, verifies its checksum and checks that a full simulated refund closes access.

## Read the poster sales journal

Open **Sales journal** from Signal Studies on Command or the Orders step in the walkthrough. Select a UTC month to see charges, refunds, fees and net movement by settlement currency. Each transaction opens its order in the saved statement. An owner-imported file enters the journal when the reporting Mac independently confirms its facts. Reports that describe the same Stripe transaction count once. If reports disagree, Studio shows both sources and withholds that transaction from the totals.

For an independent check on the reporting Mac, run `omega posters test-journal --month 2026-11`. Omega reads the isolated test merchant and its local orders, including older orders with refunds in the selected month. Compare the transaction IDs, dates, currencies and amounts with **Download journal** in Studio. Source IDs and check times identify the evidence used by each reader. The paired reporter's read-only source file is the default when the two test environment variables are absent.

Run `omega posters test-ledger --month 2026-11` for the test processor’s clearing, order receipt and fee postings in each settlement currency. Bank cash, earned revenue and tax require separate evidence. Add `--evidence-dir ./settlement-statements` to keep the exact source bytes in a private directory. A movement points to `<sourceSha256>.json`. For a refund link, open `<witnessSha256>.json` in that directory, verify its SHA-256 matches the filename, and find both transaction IDs under `movements` on the cited original order. The related charge or refund can fall in a different UTC month.

The journal covers observed test charges and refunds. A charge priced in AUD may settle in USD. The recorded net excludes bank payouts and other business costs. [Stripe balance transaction fields](https://docs.stripe.com/api/balance_transactions/object)

## Export a test order statement

Use the same sandbox key and order database as the checkout. Select the first and last **order creation days in UTC**. Omega includes every Signal Studies edition sold by this business in that account. Rerunning an earlier period includes subsequent refunds, disputes, downloads and event processing on its orders.

```sh
omega posters test-statement --from 2026-11-01 --through 2026-11-21 > test-orders.json
```

The JSON identifies each edition by its approved packet and delivery ZIP checksums. It gives the quoted amount, verified capture and successful customer refunds in the order currency, plus downloads issued and counts of processed and unresolved signed events. Amounts use integer minor units encoded as decimal strings. An unresolved payment omits both amounts and the order verification time. A confirmed zero is recorded as `"0"`.

Omega requests the balance transaction attached to the matching charge and each successful refund. Each movement carries its own settlement currency, signed amount, fee and net balance impact. Pending availability can have a verified fee. A missing fee or unexpanded transaction leaves `balanceComplete` false. A pending refund or dispute also leaves the statement partial. Customer amounts and processor movements can use different currencies. [Stripe balance transactions](https://docs.stripe.com/api/balance_transactions/object) [Stripe refund states](https://docs.stripe.com/api/refunds/object)

Coverage is `empty` when the selected account and product have no orders in the window and every row could be identified. A `partial` statement preserves independent verified orders, flags incomplete evidence, and counts any records whose scope or immutable offer could not be verified in `unresolvedScopeOrders`. A `complete` statement contains the current verified rows and all matching charge and refund movements. The export accepts up to 366 days through today, checks at most 10,000 business orders and 500 product orders, and writes at most 160,000 bytes. A period exceeding any limit fails explicitly.

## Trace poster production costs

The local order suite exercises the full buyer journey and fee attribution with a fresh PostgreSQL database. Run `make test-digital-orders` with Docker, or set `OMEGA_TEST_POSTGRES_BIN` to the directory containing an installed PostgreSQL server's `initdb`, `pg_ctl` and `createdb` tools. Both paths run the same browser and Go tests.

Each completed preparation can leave a receipt in a private cost book on the Mac. Give the operation a stable run ID. Repeating it with the same verified files returns its original receipt, including across service days. A separate preparation has its own run ID. The normal candidate JSON is still written to standard output. The cost receipt digest is written to standard error.

```sh
omega posters prepare "$SIGNAL_STUDIES_COLLECTION" --edition signal-studies-editorial-01 \
  --cost-book ./private/costs.db --cost-run editorial-proof-01 > editorial-manifest.json
omega posters costs statement --book ./private/costs.db --month 2026-11
```

The receipt references the exact candidate manifest, verified buyer archive, edition, product and run. Use `--cost-experiment` when the preparation belongs to a named experiment. The initial amount is provisional. A failed verification produces no completed preparation receipt. Supplier charges for failed or stopped work can be recorded against their own run and supporting artifact.

To record an invoice line, reservation, estimate, credit or correction, submit a [ProductionCostReceipt](../../proto/omega/v1/production_cost.proto) and its supporting file. Supply the document’s SHA-256, a stable provider and account alias, the supplier’s line ID, the UTC service date and an explicit simulated flag. A correction keeps the same source identity and includes the current receipt’s digest in `previousReceiptSha256` plus its `revisionReason`. The commands below read and write the exact bytes, including the original supporting file.

```sh
omega posters costs record cost-receipt.json supplier-document.pdf --book ./private/costs.db
omega posters costs receipt "$RECEIPT_SHA" --book ./private/costs.db > saved-receipt.json
omega posters costs evidence "$EVIDENCE_SHA" --book ./private/costs.db > saved-source.pdf
```

Amounts are signed millionths of one major currency unit. For example, AUD 2.40 is `"2400000"`. A documented zero is `"0"`. Provisional and withdrawn lines omit the amount. For dated unit prices, an estimate includes the effective date range, units, unit description and price per unit. The book checks that the service date falls within that range and the multiplication matches the estimate. An invoice or settlement can supersede the estimate. Only the current stage contributes to its currency subtotal. The statement covers the recorded lines for the selected product and UTC service month. Unreported costs have no inferred value.

A shared line lists each target’s business, product, run, artifact checksum and share in basis points. Include the edition and experiment when applicable. Shares must sum to 10,000. Remaining millionths go to the largest fractional remainders with ties resolved by target identity. Credits use the same allocation rule. The product statement includes its share and the number of targets. It retains the link to the full receipt in the owner’s local book.

The test processor ledger can record each verified charge or refund fee in the same book. It uses the balance transaction’s settlement currency and the exact source order’s archive. The original statement survives a later identical verification. A disagreement rolls back the batch and reports the affected line. Past corrections remain inspectable. Fees from this command are always simulated. The existing ledger continues to report coverage and gaps. [Stripe currency units](https://docs.stripe.com/currencies) · [Three-decimal currencies](https://support.stripe.com/questions/which-payments-methods-and-products-are-available-in-the-uae)

```sh
omega posters test-ledger --month 2026-11 --cost-book ./private/costs.db
omega posters costs statement --month 2026-11 --simulated --book ./private/costs.db
```

During a provider outage, use the previously exported native ledger and its exact source statements. Omega reconstructs the ledger, checks the order identities, merchant and immutable offers in the local order database, and preserves the earlier provider observation time. A source mismatch stops the import. The cost book records when it accepted each line.

```sh
omega posters costs recover-test-fees november-ledger.json ./november-statements/*.json --book ./private/costs.db
```

## Automatically report test orders to Studio

On the designated Mac, sign in as the user who runs the isolated checkout. Initialise its reporter and pair the printed public key in Signal Studies’ private Studio. Running `init` again returns the same public key.

```sh
omega posters reporter init
```

The default reporter directory is `~/Library/Application Support/Omega/Signal Studies Reporter`. It is owned by the current user with mode 0700. The signing seed is a 32-byte mode-0600 file called `signing.seed`. Keep that file on the Mac. Studio receives the unpadded base64url public key.

Create `source.env` in the same directory using a private editor and set its mode to 0600. Put the existing isolated Stripe test key and the read-only login for the local qualification database on two literal lines. The database URL must name a user, a database and a loopback host. Use a database user with SELECT access to `omega_digital_orders`, `omega_digital_offers` and `omega_digital_inbox`. The reporter opens read-only PostgreSQL sessions. It checks the same Stripe account and immutable orders as `test-statement`.

```text
OMEGA_POSTER_STRIPE_TEST_KEY=<isolated test key>
OMEGA_POSTER_COMMERCE_DATABASE_URL=postgres://<read-only user>:<encoded password>@127.0.0.1:<port>/<database>?sslmode=disable
```

Enter the actual values directly in that private file. The reader treats quotes, dollar signs and equal signs inside values literally. Use `--credentials /absolute/path/to/file` on `run` or `install` to select another owner-only file. Use `--directory` to choose the signing directory.

Run a dated report, or use `--days 30` for a rolling window through today in UTC. A successful run prints Studio’s receipt with its `saved` or `unchanged` outcome, statement ID and check time. Omega verifies that the receipt identifies this product, period and check time. An unchanged result can point to an earlier saved statement for the same period.

```sh
omega posters reporter run --from 2026-11-20 --through 2026-11-21
omega posters reporter install --executable "$(command -v omega)" --days 30
```

The per-user LaunchAgent `com.omega.signal-studies-reporter` runs at login and every five minutes while the Mac is awake and the user is signed in. Its configuration contains local paths and the day count. Scheduled output is discarded. Open the private Studio project to see the last accepted check, or run the reporter manually for a receipt. To inspect launchd's last exit status, run `launchctl print "gui/$(id -u)/com.omega.signal-studies-reporter"`. To stop reporting across future logins, run `omega posters reporter disable`. To resume after pairing, run `install` again.

If a rolling period advances past dates that Studio previously found incomplete on this connection, Studio can ask for those exact dates in its acknowledgement. The Mac verifies at most one earlier period per check, within its configured number of days. It signs the historical statement separately. The ordinary receipt still describes the current period, including when a provider limit delays the recheck. A one-time run with explicit dates sends only the selected period. Order watch retains the original finding and the signed evidence used to close it.

When Stripe rate-limits a merchant, order or refund read, Omega defers that statement. Studio keeps the last accepted coverage and its original verification time. The next scheduled check can retry using the same test account.

Omega posts the exact v1 statement JSON bytes to the fixed Signal Studies receiver. It signs the protocol version, HTTP method, full endpoint, Unix issue time and SHA-256 of the body with Ed25519. Transient connection failures, HTTP 408/429 and server errors get up to two retries with the same statement. Redirects end the attempt. Source or permission errors surface through the command's exit status. The next scheduled run rechecks the rolling window.
