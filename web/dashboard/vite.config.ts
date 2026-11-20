import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { businessStudioCommand } from '../../dashboard/studio-entry'

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  define: {
    'import.meta.env.BUSINESS_STUDIO_COMMAND': JSON.stringify(
      businessStudioCommand(loadEnv(mode, '.', 'OMEGA_BUSINESS_STUDIO_ORIGIN').OMEGA_BUSINESS_STUDIO_ORIGIN)
    ),
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/omega.v1': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
}))
