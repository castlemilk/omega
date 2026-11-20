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
  test(`opens Command by keyboard and returns to the original dashboard at ${width}px`, async ({ page, baseURL }) => {
    await page.setViewportSize({ width, height: 900 })
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
    await link.focus()
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
  })
}
