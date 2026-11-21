// Called by TestDigitalOrderBrowser. The fixture provider runs only in that test.
const assert = require("node:assert/strict");
const { readFile } = require("node:fs/promises");
const path = require("node:path");
const { chromium } = require(
  require.resolve("playwright", {
    paths: [path.resolve(__dirname, "../web/dashboard")],
  }),
);

async function run() {
  const origin = process.argv[2];
  const browser = await chromium.launch();
  try {
    const buyer = await browser.newContext({ acceptDownloads: true });
    const page = await buyer.newPage();
    await page.goto(origin);
    await page.getByRole("button", { name: "Start test checkout" }).click();
    await page.getByRole("heading", { name: "Awaiting payment" }).waitFor();
    const orderURL = page.url();
    const id = new URL(orderURL).pathname.split("/").pop();
    assert.match(id, /^[a-f0-9-]{36}$/);
    assert.equal(
      await page.getByRole("button", { name: "Download the six PDFs" }).count(),
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
    await change("paid");
    await page.getByRole("button", { name: "Check payment status" }).click();
    await page.getByRole("heading", { name: "Payment confirmed" }).waitFor();
    const downloadButton = page.getByRole("button", {
      name: "Download the six PDFs",
    });
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      downloadButton.click(),
    ]);
    assert.equal(download.suggestedFilename(), "edition.zip");
    assert.equal(
      await readFile(await download.path(), "utf8"),
      "frozen first edition",
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
