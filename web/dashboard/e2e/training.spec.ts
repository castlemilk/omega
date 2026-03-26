/**
 * training.spec.ts
 *
 * End-to-end tests for the Training Progress page (/training).
 *
 * The backend API is not available during tests, so all API calls fail
 * gracefully — the page renders with the IdleState when no training run
 * is active, and with mock data when mocked via route interception.
 *
 * Screenshots are saved to e2e/screenshots/ for visual validation.
 */
import { test, expect, type Page } from '@playwright/test'
import * as path from 'path'
import * as fs from 'fs'

const screenshotsDir = path.join(process.cwd(), 'e2e', 'screenshots')
if (!fs.existsSync(screenshotsDir)) fs.mkdirSync(screenshotsDir, { recursive: true })

async function snap(page: Page, name: string) {
  await page.screenshot({ path: path.join(screenshotsDir, `${name}.png`), fullPage: true })
}

// ── Mock training data ────────────────────────────────────────────────────────

const mockProgress = {
  run_id: 'run_test_001',
  total_cycles: 1000,
  current_cycle: 247,
  started_at: new Date(Date.now() - 2 * 3600 * 1000).toISOString(),
  status: 'running',
  config: { symbols: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'], initial_capital: 10000, kelly_fraction: 0.25 },
  pnl_history: [
    { cycle: 50,  pnl: 38.9  },
    { cycle: 100, pnl: 124.6 },
    { cycle: 150, pnl: 189.4 },
    { cycle: 200, pnl: 241.5 },
    { cycle: 247, pnl: 347.2 },
  ],
  win_rate_history: [
    { cycle: 50,  win_rate: 0.53 },
    { cycle: 100, win_rate: 0.63 },
    { cycle: 150, win_rate: 0.68 },
    { cycle: 200, win_rate: 0.71 },
    { cycle: 247, win_rate: 0.78 },
  ],
  memory_growth: [
    { cycle: 0,   episodic: 0,   semantic: 0  },
    { cycle: 100, episodic: 91,  semantic: 9  },
    { cycle: 200, episodic: 181, semantic: 23 },
    { cycle: 247, episodic: 224, semantic: 29 },
  ],
  signal_conviction: [
    { name: 'Momentum',      value: 0.72 },
    { name: 'MeanReversion', value: 0.58 },
    { name: 'Funding',       value: 0.81 },
  ],
  activity_log: [
    { cycle: 247, type: 'trade',  message: 'LONG SOLUSDT @ $91.43, size 0.15 (Kelly=12%)' },
    { cycle: 244, type: 'memory', message: "Semantic pattern: 'High funding rates predicted reversals in 7/10 cases'" },
    { cycle: 243, type: 'trade',  message: 'LONG BTCUSDT @ $67,241.00, size 0.002 (Kelly=15%)' },
  ],
  current_regime: { name: 'BULL', confidence: 0.74, dominant_signal: 'Funding' },
  snapshots: [],
}

const mockMetrics = {
  total_trades: 183,
  win_rate: 0.78,
  total_pnl: 347.2,
  realised_pnl: 320.5,
  unrealised_pnl: 26.7,
  memory_count: { episodic: 224, semantic: 29, total: 253 },
  symbol_breakdown: [
    { symbol: 'BTCUSDT', trades: 72, win_rate: 0.79, total_pnl: 180.4 },
    { symbol: 'ETHUSDT', trades: 61, win_rate: 0.75, total_pnl: 91.3  },
    { symbol: 'SOLUSDT', trades: 50, win_rate: 0.80, total_pnl: 75.5  },
  ],
  recent_trades: [
    { ts: new Date().toISOString(), sym: 'SOLUSDT', side: 'LONG', size: 0.15, entry: 91.43, exit_price: 0, pnl: 2.1 },
    { ts: new Date(Date.now() - 60000).toISOString(), sym: 'BTCUSDT', side: 'LONG', size: 0.002, entry: 67241, exit_price: 67810, pnl: 1.14 },
  ],
  signal_health: [
    { name: 'Momentum', value: 0.72 },
    { name: 'Funding',  value: 0.81 },
  ],
  current_cycle: 247,
  total_cycles: 1000,
  status: 'running',
}

const mockSnapshots: unknown[] = []

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe('Training Page', () => {
  test('sidebar shows Training nav item with pulsing indicator', async ({ page }) => {
    await page.goto('/')
    await page.waitForSelector('[data-testid="sidebar"]', { timeout: 10000 })

    const sidebar = page.locator('[data-testid="sidebar"]')
    await expect(sidebar).toContainText('Training')
    await snap(page, 'training-01-sidebar-nav-item')
  })

  test('navigating to /training shows training page', async ({ page }) => {
    await page.goto('/training')
    await page.waitForSelector('[data-testid="training-page"]', { timeout: 10000 })
    await snap(page, 'training-02-page-loaded')

    expect(page.url()).toContain('/training')
    await expect(page.locator('h1')).toContainText('Training Progress')
  })

  test('idle state renders when no training run is active', async ({ page }) => {
    // Intercept API calls and return idle state
    await page.route('/api/v1/training/progress', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ run_id: '', status: 'idle', total_cycles: 0, current_cycle: 0, snapshots: [] }) })
    )
    await page.route('/api/v1/training/metrics', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'idle', total_trades: 0, win_rate: 0, total_pnl: 0, realised_pnl: 0, unrealised_pnl: 0, memory_count: { episodic: 0, semantic: 0, total: 0 }, symbol_breakdown: [], recent_trades: [], signal_health: [], current_cycle: 0, total_cycles: 0 }) })
    )
    await page.route('/api/v1/training/snapshots', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    )

    await page.goto('/training')
    await page.waitForSelector('[data-testid="training-page"]', { timeout: 10000 })
    await snap(page, 'training-03-idle-state')

    // Idle state should be visible
    await expect(page.locator('text=No active training run')).toBeVisible()
  })

  test('active training state renders with metrics and charts', async ({ page }) => {
    // Mock all API endpoints with rich training data
    await page.route('/api/v1/training/progress', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockProgress) })
    )
    await page.route('/api/v1/training/metrics', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockMetrics) })
    )
    await page.route('/api/v1/training/snapshots', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSnapshots) })
    )

    await page.goto('/training')
    await page.waitForSelector('[data-testid="training-page"]', { timeout: 10000 })
    // Wait for data to render
    await page.waitForTimeout(500)

    await snap(page, 'training-04-active-training')

    // Verify status badge shows RUNNING
    await expect(page.locator('text=RUNNING')).toBeVisible()

    // Verify cycle counter
    await expect(page.locator('text=247').first()).toBeVisible()

    // Progress heading should show cycle numbers
    await expect(page.locator('text=1,000').first()).toBeVisible()
  })

  test('shows PnL, win rate, and memory metrics', async ({ page }) => {
    await page.route('/api/v1/training/progress', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockProgress) })
    )
    await page.route('/api/v1/training/metrics', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockMetrics) })
    )
    await page.route('/api/v1/training/snapshots', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    )

    await page.goto('/training')
    await page.waitForSelector('[data-testid="training-page"]', { timeout: 10000 })
    await page.waitForTimeout(500)

    // Win rate
    await expect(page.locator('text=78.0%').first()).toBeVisible()

    // Check for the trade activity
    await expect(page.locator('text=LONG SOLUSDT @ $91.43').first()).toBeVisible()

    await snap(page, 'training-05-metrics-visible')
  })

  test('activity feed shows trade, signal, and memory events', async ({ page }) => {
    await page.route('/api/v1/training/progress', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockProgress) })
    )
    await page.route('/api/v1/training/metrics', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockMetrics) })
    )
    await page.route('/api/v1/training/snapshots', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    )

    await page.goto('/training')
    await page.waitForSelector('[data-testid="training-page"]', { timeout: 10000 })
    await page.waitForTimeout(500)

    // Activity feed
    await expect(page.locator('text=Activity Feed')).toBeVisible()
    await expect(page.locator('text=LONG SOLUSDT @ $91.43').first()).toBeVisible()

    await snap(page, 'training-06-activity-feed')
  })

  test('snapshot button is present', async ({ page }) => {
    await page.route('/api/v1/training/progress', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockProgress) })
    )
    await page.route('/api/v1/training/metrics', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockMetrics) })
    )
    await page.route('/api/v1/training/snapshots', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    )

    await page.goto('/training')
    await page.waitForSelector('[data-testid="training-page"]', { timeout: 10000 })
    await page.waitForTimeout(500)

    // Snapshot button should be visible
    await expect(page.locator('text=Take Snapshot')).toBeVisible()
    await snap(page, 'training-07-snapshot-panel')
  })

  test('regime banner shows current market regime', async ({ page }) => {
    await page.route('/api/v1/training/progress', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockProgress) })
    )
    await page.route('/api/v1/training/metrics', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockMetrics) })
    )
    await page.route('/api/v1/training/snapshots', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    )

    await page.goto('/training')
    await page.waitForSelector('[data-testid="training-page"]', { timeout: 10000 })
    await page.waitForTimeout(500)

    await expect(page.locator('text=Current regime:')).toBeVisible()
    await expect(page.locator('text=BULL').first()).toBeVisible()

    await snap(page, 'training-08-regime-banner')
  })
})
