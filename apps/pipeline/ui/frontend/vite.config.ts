import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

const backendPort = process.env.P2K_BACKEND_PORT ?? '8000'
const caPort = process.env.CA_PORT ?? '5000'
const frontendPort = Number(process.env.P2K_FRONTEND_PORT ?? '5173')

const BASE_PATH = (process.env.VITE_BASE_PATH ?? '/app').replace(/\/$/, '')

export default defineConfig({
  base: `${BASE_PATH}/`,
  plugins: [react()],
  // Use a unique assets dir so kg-frontend's hashed bundles don't collide
  // with the suite-shell's /app/assets/ when both apps are mounted
  // under the same base path via the suite-shell nginx proxy.
  build: {
    assetsDir: 'kg-assets',
  },
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  server: {
    port: frontendPort,
    proxy: {
      '/api/ca': {
        target: `http://localhost:${caPort}`,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api\/ca/, '/app/api'),
      },
      '/api': `http://localhost:${backendPort}`,
      '/ws': { target: `ws://localhost:${backendPort}`, ws: true },
    },
  },
})
