/**
 * project-switcher.spec.ts
 *
 * Journey: open project switcher dropdown → verify project list →
 * select a project → verify URL changes → verify sidebar updates.
 *
 * Every step captures a screenshot to e2e/screenshots/ for visual validation.
 */
import { test, expect, type Page } from '@playwright/test'
import * as path from 'path'
import * as fs from 'fs'

const screenshotsDir = path.join(process.cwd(), 'e2e', 'screenshots')
if (!fs.existsSync(screenshotsDir)) fs.mkdirSync(screenshotsDir, { recursive: true })

async function snap(page: Page, name: string) {
  await page.screenshot({ path: path.join(screenshotsDir, `${name}.png`), fullPage: true })
}

test.describe('Project Switcher', () => {
  test('project switcher button is visible in sidebar', async ({ page }) => {
    await page.goto('/')
    await page.waitForSelector('[data-testid="project-switcher-trigger"]', { timeout: 10000 })
    await snap(page, 'ps-01-switcher-visible')

    const btn = page.locator('[data-testid="project-switcher-trigger"]')
    await expect(btn).toBeVisible()
  })

  test('clicking project switcher opens dropdown', async ({ page }) => {
    await page.goto('/')
    await page.waitForSelector('[data-testid="project-switcher-trigger"]')

    await page.click('[data-testid="project-switcher-trigger"]')
    await page.waitForSelector('[data-testid="project-switcher-dropdown"]')
    await snap(page, 'ps-02-dropdown-open')

    await expect(page.locator('[data-testid="project-switcher-dropdown"]')).toBeVisible()
  })

  test('dropdown shows at least the Victoria project', async ({ page }) => {
    await page.goto('/')
    await page.waitForSelector('[data-testid="project-switcher-trigger"]')

    await page.click('[data-testid="project-switcher-trigger"]')
    await page.waitForSelector('[data-testid="project-switcher-dropdown"]')
    await snap(page, 'ps-03-dropdown-with-projects')

    // Victoria fallback project is always seeded
    await expect(page.locator('[data-testid="project-switcher-dropdown"]')).toContainText('Victoria')
  })

  test('selecting Victoria from switcher navigates to /projects/victoria', async ({ page }) => {
    await page.goto('/')
    await page.waitForSelector('[data-testid="project-switcher-trigger"]')

    await page.click('[data-testid="project-switcher-trigger"]')
    await page.waitForSelector('[data-testid="project-option-victoria"]')
    await snap(page, 'ps-04-before-select')

    await page.click('[data-testid="project-option-victoria"]')
    await page.waitForSelector('[data-testid="project-overview"]', { timeout: 10000 })
    await snap(page, 'ps-05-after-select-victoria')

    expect(page.url()).toContain('/projects/victoria')
  })

  test('selected project is highlighted in dropdown', async ({ page }) => {
    await page.goto('/projects/victoria')
    await page.waitForSelector('[data-testid="sidebar"]')

    await page.click('[data-testid="project-switcher-trigger"]')
    await page.waitForSelector('[data-testid="project-switcher-dropdown"]')
    await snap(page, 'ps-06-selected-project-highlighted')

    // The active option should have aria-selected=true
    const activeOption = page.locator('[data-testid="project-option-victoria"][aria-selected="true"]')
    await expect(activeOption).toBeVisible()
  })

  test('clicking outside dropdown closes it', async ({ page }) => {
    await page.goto('/')
    await page.waitForSelector('[data-testid="project-switcher-trigger"]')

    await page.click('[data-testid="project-switcher-trigger"]')
    await page.waitForSelector('[data-testid="project-switcher-dropdown"]')

    // Click outside
    await page.click('h1')
    await page.waitForTimeout(200)
    await snap(page, 'ps-07-dropdown-closed')

    await expect(page.locator('[data-testid="project-switcher-dropdown"]')).not.toBeVisible()
  })

  test('project-specific nav updates after switching project', async ({ page }) => {
    await page.goto('/')
    await page.waitForSelector('[data-testid="project-switcher-trigger"]')

    // Select victoria
    await page.click('[data-testid="project-switcher-trigger"]')
    await page.click('[data-testid="project-option-victoria"]')
    await page.waitForSelector('[data-testid="project-overview"]', { timeout: 10000 })
    await snap(page, 'ps-08-victoria-nav-shown')

    // Should see Victoria-specific nav items
    await expect(page.locator('[data-testid="sidebar"]')).toContainText('Trading')
    await expect(page.locator('[data-testid="sidebar"]')).toContainText('Signals')
    await expect(page.locator('[data-testid="sidebar"]')).toContainText('Positions')
  })
})
