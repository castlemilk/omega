import { defineConfig } from '@playwright/test'

const dashboards = [
  { name: 'dashboard', cwd: '../../dashboard', port: 15173 },
  { name: 'web-dashboard', cwd: '.', port: 15174 },
]

export default defineConfig({
  testDir: './studio-e2e',
  outputDir: './e2e-results/studio',
  use: { trace: 'retain-on-failure' },
  projects: dashboards.map(({ name, port }) => ({
    name, use: { baseURL: `http://127.0.0.1:${port}` },
  })),
  webServer: dashboards.map(({ cwd, port }) => ({
    cwd,
    command: `npm run dev -- --host 127.0.0.1 --port ${port} --strictPort`,
    url: `http://127.0.0.1:${port}`,
    env: { OMEGA_BUSINESS_STUDIO_ORIGIN: 'https://studio.example.test' },
  })),
})
