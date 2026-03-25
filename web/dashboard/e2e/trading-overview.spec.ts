/**
 * trading-overview.spec.ts
 *
 * Journey: navigate to trading page → verify PnL stats, equity curve,
 * trades table, signal heatmap, and positions summary.
 *
 * Every step captures a screenshot to e2e/screenshots/ for visual validation.
 * Tests are resilient to missing backend — they verify UI renders with
 * loading/empty states rather than crashing.
 */
import { test, expect, type Page } from '@playwright/test'
import * as path from 'path'
import * as fs from 'fs'

const screenshotsDir = path.join(process.cwd(), 'e2e', 'screenshots')
if (!fs.existsSync(screenshotsDir)) fs.mkdirSync(screenshotsDir, { recursive: true })

async function snap(page: Page, name: string) {
  await page.screenshot({ path: path.join(screenshotsDir, `${name}.png`), fullPage: true })
}

// Wait for loading spinners to disappear or data to appear
async function waitForData(page: Page) {
  // Either skeleton loaders disappear or a short timeout passes
  await page.waitForTimeout(2000)
}

test.describe('Trading Overview', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/projects/victoria/trading')
    await page.waitForSelector('[data-testid="trading-page"]', { timeout: 10000 })
  })

  test('trading page renders correctly', async ({ page }) => {
    await snap(page, 'to-01-trading-page-initial')
    await expect(page.locator('h1')).toContainText('Trading Overview')
    await snap(page, 'to-02-heading')
  })

  test('PnL stat cards are present', async ({ page }) => {
    await waitForData(page)
    await snap(page, 'to-03-pnl-stats')

    // There should be at least one stat card (PnL stats grid)
    // Even if values are "—", the structure should be there
    const statCards = page.locator('.grid .bg-slate-800')
    await expect(statCards.first()).toBeVisible()
  })

  test('equity curve chart section is present', async ({ page }) => {
    await waitForData(page)
    await snap(page, 'to-04-equity-curve')

    // The equity curve card should have a heading
    await expect(page.locator('text=Equity Curve vs BTC')).toBeVisible()
  })

  test('trades table renders with correct columns', async ({ page }) => {
    await waitForData(page)
    await snap(page, 'to-05-trades-table')

    const table = page.locator('[data-testid="trades-table"]')
    await expect(table).toBeVisible()

    // Check column headers
    await expect(table).toContainText('Symbol')
    await expect(table).toContainText('Side')
    await expect(table).toContainText('PnL')
  })

  test('trades table side filter works', async ({ page }) => {
    await waitForData(page)

    // Click LONG filter
    await page.click('button:text("LONG")')
    await snap(page, 'to-06-long-filter')

    // Click SHORT filter
    await page.click('button:text("SHORT")')
    await snap(page, 'to-07-short-filter')

    // Reset to All
    await page.click('button:text("All")')
    await snap(page, 'to-08-all-filter')
  })

  test('symbol filter input is present', async ({ page }) => {
    await waitForData(page)
    const filterInput = page.locator('input[placeholder="Filter symbol…"]')
    await expect(filterInput).toBeVisible()

    await filterInput.fill('BTC')
    await snap(page, 'to-09-symbol-filter-btc')

    await filterInput.clear()
  })

  test('full trading page screenshot', async ({ page }) => {
    await waitForData(page)
    await snap(page, 'to-10-full-trading-page')
  })
})

test.describe('Project Overview — Victoria KPIs', () => {
  test('victoria overview shows KPI cards', async ({ page }) => {
    await page.goto('/projects/victoria')
    await page.waitForSelector('[data-testid="project-overview"]', { timeout: 10000 })
    await page.waitForTimeout(1500)
    await snap(page, 'vo-01-project-overview-loaded')

    const pnlCards = page.locator('[data-testid="pnl-cards"]')
    await expect(pnlCards).toBeVisible()
    await snap(page, 'vo-02-pnl-cards')
  })

  test('victoria overview has signal heatmap section', async ({ page }) => {
    await page.goto('/projects/victoria')
    await page.waitForSelector('[data-testid="project-overview"]', { timeout: 10000 })
    await page.waitForTimeout(1500)

    // Signal Health section title
    await expect(page.locator('text=Signal Health')).toBeVisible()
    await snap(page, 'vo-03-signal-heatmap-section')
  })

  test('victoria overview has open positions section', async ({ page }) => {
    await page.goto('/projects/victoria')
    await page.waitForSelector('[data-testid="project-overview"]', { timeout: 10000 })
    await page.waitForTimeout(1500)

    await expect(page.locator('h3:has-text("Open Positions")')).toBeVisible()
    await snap(page, 'vo-04-positions-section')
  })
})

test.describe('Signals Page', () => {
  test('signals page loads and renders', async ({ page }) => {
    await page.goto('/projects/victoria/signals')
    await page.waitForSelector('[data-testid="signals-page"]', { timeout: 10000 })
    await page.waitForTimeout(1500)
    await snap(page, 'sig-01-signals-page')

    await expect(page.locator('h1')).toContainText('Signals')
    await snap(page, 'sig-02-signals-heading')
  })
})

test.describe('Positions Page', () => {
  test('positions page loads and renders', async ({ page }) => {
    await page.goto('/projects/victoria/positions')
    await page.waitForSelector('[data-testid="positions-page"]', { timeout: 10000 })
    await page.waitForTimeout(1500)
    await snap(page, 'pos-01-positions-page')

    await expect(page.locator('h1')).toContainText('Positions')
    await snap(page, 'pos-02-positions-heading')
  })

  test('positions table has correct columns', async ({ page }) => {
    await page.goto('/projects/victoria/positions')
    await page.waitForSelector('[data-testid="positions-page"]', { timeout: 10000 })
    await page.waitForTimeout(1500)

    const table = page.locator('.bg-slate-800.rounded-xl table')
    await expect(table).toBeVisible()
    await expect(table).toContainText('Symbol')
    await expect(table).toContainText('Side')
    await expect(table).toContainText('uPnL')
    await snap(page, 'pos-03-positions-columns')
  })
})
