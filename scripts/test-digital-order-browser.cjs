// Called by TestDigitalOrderBrowser. The fixture provider runs only in that test.
const assert = require("node:assert/strict");
const { createHash } = require("node:crypto");
const { readFileSync } = require("node:fs");
const { readFile } = require("node:fs/promises");
const path = require("node:path");
const { chromium } = require(
  require.resolve("playwright", {
    paths: [path.resolve(__dirname, "../web/dashboard")],
  }),
);

async function run() {
  const { origin, offer } = JSON.parse(readFileSync(0, "utf8"));
  const editorial = ["signal-studies-editorial-01", "signal-studies-caption-01"].includes(offer.edition);
  const downloadLabel = editorial
    ? "Download the print ZIP"
    : "Download the six PDFs";
  const browser = await chromium.launch();
  try {
    const buyer = await browser.newContext({ acceptDownloads: true });
    const page = await buyer.newPage();
    await page.goto(origin);
    if (editorial) {
      const lead = page.getByRole("img", {
        name: "Phase portrait, the A4 print from the approved edition",
      });
      await lead.evaluate((image) => image.decode());
    }
    await page.getByRole("button", { name: "Start test checkout" }).click();
    await page.getByRole("heading", { name: "Awaiting payment" }).waitFor();
    const orderURL = page.url();
    const id = new URL(orderURL).pathname.split("/").pop();
    assert.match(id, /^[a-f0-9-]{36}$/);
    assert.equal(
      await page.getByRole("button", { name: downloadLabel }).count(),
      0,
    );
    const other = await browser.newContext();
    assert.equal(
      (await other.request.get(orderURL + "/receipt")).status(),
      404,
    );
    assert.equal(
      (
        await buyer.request.post(orderURL + "/download", {
          headers: { Origin: "https://other.example" },
        })
      ).status(),
      403,
    );
    const change = async (status) => {
      assert.equal(
        (
          await other.request.post(origin + "/fixture/" + id + "/" + status)
        ).status(),
        204,
      );
    };
    await change("decline");
    await page.getByRole("button", { name: "Check payment status" }).click();
    await page.getByRole("heading", { name: "Payment failed" }).waitFor();
    assert.equal(
      await page.getByRole("button", { name: downloadLabel }).count(),
      0,
    );
    await page.getByRole("button", { name: "Resume checkout" }).click();
    assert.equal(page.url(), orderURL);
    await change("paid");
    await page.getByRole("button", { name: "Check payment status" }).click();
    await page.getByRole("heading", { name: "Payment confirmed" }).waitFor();
    const downloadButton = page.getByRole("button", { name: downloadLabel });
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      downloadButton.click(),
    ]);
    assert.equal(download.suggestedFilename(), offer.archiveName);
    const downloaded = await readFile(await download.path());
    assert.equal(
      createHash("sha256").update(downloaded).digest("hex"),
      offer.archiveSha256,
    );
    await change("refund");
    const [closed] = await Promise.all([
      page.waitForResponse(orderURL + "/download"),
      downloadButton.click(),
    ]);
    assert.equal(closed.status(), 403);
    await page.goto(orderURL);
    await page.getByRole("heading", { name: "Payment refunded" }).waitFor();
    assert.equal(await downloadButton.count(), 0);
    await page.getByText("Provider evidence", { exact: true }).click();
    const link = page.getByRole("link", { name: "View test order receipt" });
    const [response] = await Promise.all([
      page.waitForResponse(orderURL + "/receipt"),
      link.click(),
    ]);
    const receipt = await response.json();
    assert.deepEqual(receipt.offer, offer);
    assert.equal(receipt.payment, "DIGITAL_PAYMENT_STATE_REFUNDED");
    assert.equal(receipt.refundedMinor, "1200");
    assert.equal(receipt.downloadsIssued, 1);
    assert.ok(receipt.testMode);
  } finally {
    await browser.close();
  }
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
