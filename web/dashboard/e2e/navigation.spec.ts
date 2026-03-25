/**
 * navigation.spec.ts
 *
 * Journey: load app → see global overview → navigate to project → check
 * per-project nav → navigate between pages → verify sidebar and breadcrumbs.
 *
 * Every step captures a screenshot to e2e/screenshots/ for visual validation.
 */
import { test, expect, type Page } from '@playwright/test'
import * as path from 'path'
import * as fs from 'fs'

// Ensure screenshots dir exists
const screenshotsDir = path.join(process.cwd(), 'e2e', 'screenshots')
if (!fs.existsSync(screenshotsDir)) fs.mkdirSync(screenshotsDir, { recursive: true })

async function snap(page: Page, name: string) {
  await page.screenshot({ path: path.join(screenshotsDir, `${name}.png`), fullPage: true })
}

test.describe('Navigation', () => {
  test('loads global overview on first visit', async ({ page }) => {
    await page.goto('/')

    // Wait for the overview to render
    await page.waitForSelector('[data-testid="global-overview"]', { timeout: 10000 })
    await snap(page, '01-global-overview-loaded')

    // Sidebar should be visible with Omega branding
    const sidebar = page.locator('[data-testid="sidebar"]')
    await expect(sidebar).toBeVisible()
    await snap(page, '02-sidebar-visible')

    // Page heading
    await expect(page.locator('h1')).toContainText('Platform Overview')
    await snap(page, '03-page-heading')
  })

  test('global overview shows system metrics section', async ({ page }) => {
    await page.goto('/')
    await page.waitForSelector('[data-testid="global-overview"]', { timeout: 10000 })

    // Metric tiles should be present (even if values are "—" due to backend being unavailable)
    const metrics = page.locator('[data-testid="system-metrics"]')
    await expect(metrics).toBeVisible()
    await snap(page, '04-system-metrics')
  })

  test('navigating to /projects/victoria shows project overview', async ({ page }) => {
    await page.goto('/projects/victoria')
    await page.waitForSelector('[data-testid="project-overview"]', { timeout: 10000 })
    await snap(page, '05-victoria-project-overview')

    await expect(page.locator('h1')).toContainText(/victoria/i)
    await snap(page, '06-victoria-heading')
  })

  test('per-project nav appears when on a project route', async ({ page }) => {
    await page.goto('/projects/victoria')
    await page.waitForSelector('[data-testid="sidebar"]')

    // Project-specific nav items should be in sidebar
    await expect(page.locator('[data-testid="sidebar"]')).toContainText('Trading')
    await expect(page.locator('[data-testid="sidebar"]')).toContainText('Signals')
    await expect(page.locator('[data-testid="sidebar"]')).toContainText('Positions')
    await snap(page, '07-per-project-nav')
  })

  test('clicking Trading nav item navigates to /projects/victoria/trading', async ({ page }) => {
    await page.goto('/projects/victoria')
    await page.waitForSelector('[data-testid="sidebar"]')

    await page.click('text=Trading')
    await page.waitForSelector('[data-testid="trading-page"]', { timeout: 10000 })
    await snap(page, '08-trading-page')

    expect(page.url()).toContain('/projects/victoria/trading')
    await expect(page.locator('h1')).toContainText('Trading Overview')
  })

  test('clicking Signals nav item navigates to signals page', async ({ page }) => {
    await page.goto('/projects/victoria')
    await page.waitForSelector('[data-testid="sidebar"]')

    await page.click('text=Signals')
    await page.waitForSelector('[data-testid="signals-page"]', { timeout: 10000 })
    await snap(page, '09-signals-page')

    expect(page.url()).toContain('/projects/victoria/signals')
  })

  test('clicking Positions nav item navigates to positions page', async ({ page }) => {
    await page.goto('/projects/victoria')
    await page.waitForSelector('[data-testid="sidebar"]')

    await page.click('text=Positions')
    await page.waitForSelector('[data-testid="positions-page"]', { timeout: 10000 })
    await snap(page, '10-positions-page')

    expect(page.url()).toContain('/projects/victoria/positions')
  })

  test('clicking Overview in global nav returns to global overview', async ({ page }) => {
    await page.goto('/projects/victoria/trading')
    await page.waitForSelector('[data-testid="trading-page"]')

    // Click "Overview" in the Platform section (first nav item)
    await page.click('nav >> text=Overview >> nth=0')
    await page.waitForSelector('[data-testid="global-overview"]', { timeout: 10000 })
    await snap(page, '11-back-to-global-overview')

    expect(page.url()).toMatch(/\/$|\/index\.html$/)
  })

  test('sidebar collapse/expand works', async ({ page }) => {
    await page.goto('/')
    await page.waitForSelector('[data-testid="sidebar"]')

    // Collapse
    await page.click('[data-testid="sidebar-collapse-btn"]')
    await page.waitForTimeout(300) // transition
    await snap(page, '12-sidebar-collapsed')

    // Expand
    await page.click('[data-testid="sidebar-collapse-btn"]')
    await page.waitForTimeout(300)
    await snap(page, '13-sidebar-expanded')
  })

  test('unknown route redirects to global overview', async ({ page }) => {
    await page.goto('/this/does/not/exist')
    await page.waitForSelector('[data-testid="global-overview"]', { timeout: 10000 })
    await snap(page, '14-redirect-to-overview')
  })
})
