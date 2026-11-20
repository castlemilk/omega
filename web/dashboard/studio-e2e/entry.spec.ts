import { test, expect } from '@playwright/test'
import { businessStudioCommand } from '../../../dashboard/studio-entry'

test('only a configured HTTPS origin supplies a destination', () => {
  expect(businessStudioCommand(undefined)).toBeNull()
  expect(businessStudioCommand('')).toBeNull()
  expect(businessStudioCommand('https://studio.example.test/')).toBe('https://studio.example.test/command')
  for (const origin of ['studio.example.test', 'http://studio.example.test', 'https://studio.example.test/other',
    'https://studio.example.test?business=one', 'https://studio.example.test/#scope', 'https://user@studio.example.test']) {
    expect(() => businessStudioCommand(origin)).toThrow('OMEGA_BUSINESS_STUDIO_ORIGIN')
  }
})

for (const width of [390, 1440]) {
  test(`opens Command by keyboard and returns to the original dashboard at ${width}px`, async ({ page, baseURL }, testInfo) => {
    await page.setViewportSize({ width, height: width === 390 ? 640 : 900 })
    // The private service is independently tested. Capture what actually leaves this dashboard.
    const destination = 'https://studio.example.test/command'
    await page.route(url => url.origin === baseURL && /^\/(?:api\/|omega\.v1\.)/.test(url.pathname),
      route => route.fulfill({ status: 503, body: 'Runtime fixture is offline' }))
    await page.route('https://studio.example.test/**', route => route.fulfill({
      contentType: 'text/html', body: '<title>Studio fixture</title><main>Command fixture</main>',
    }))
    await page.goto('/settings?project=runtime-only')
    const original = page.url()
    const link = page.getByRole('link', { name: 'Business Studio', exact: true })
    await expect(link).toBeInViewport()
    await expect(link).toHaveAttribute('href', destination)
    if (width === 390) {
      expect(await page.locator('main').evaluate(el => el.getBoundingClientRect().width)).toBe(width)
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width)
    }
    for (let i = 0; i < 12 && !(await link.evaluate(el => el === document.activeElement)); i++) {
      await page.keyboard.press('Tab')
    }
    await expect(link).toBeFocused()
    const [request] = await Promise.all([
      page.waitForRequest(req => req.url() === destination),
      page.keyboard.press('Enter'),
    ])
    expect(request.isNavigationRequest()).toBe(true)
    expect(await request.headerValue('referer')).toBeNull()
    await expect(page).toHaveTitle('Studio fixture')
    await page.goBack()
    await expect(page).toHaveURL(original)
    await expect(link).toBeVisible()
    if (width === 390) {
      const menu = page.getByRole('button', { name: 'Navigation menu' })
      await menu.click()
      await expect(menu).toHaveAttribute('aria-expanded', 'true')
      await expect(page.getByRole('link', { name: 'Settings', exact: true })).toBeVisible()
      await page.keyboard.press('Escape')
      await expect(menu).toBeFocused()
      await expect(menu).toHaveAttribute('aria-expanded', 'false')
      await menu.click()
      const home = page.getByRole('link', { name: testInfo.project.name === 'dashboard' ? 'Home' : 'Overview', exact: true }).first()
      await home.click()
      await expect(page).toHaveURL(baseURL + '/')
      await expect(menu).toHaveAttribute('aria-expanded', 'false')
      if (testInfo.project.name === 'dashboard') {
        await expect(page.getByText('Open Issues', { exact: true })).toBeInViewport({ ratio: 1 })
      }
    } else if (testInfo.project.name === 'web-dashboard') {
      await page.goto('/projects/victoria')
      await page.getByTestId('sidebar-collapse-btn').click()
      const trading = page.getByRole('link', { name: 'Trading', exact: true })
      await expect(trading).toBeVisible()
      const tradingIcon = await trading.locator('svg').innerHTML()
      const studioIcon = await link.locator('svg').innerHTML()
      expect(studioIcon).not.toBe('')
      expect(studioIcon).not.toBe(tradingIcon)
    }
  })
}
