import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

const KG_BACKEND_PORT = process.env.KG_BACKEND_PORT ?? '8000'
const KG_FRONTEND_PORT = process.env.KG_FRONTEND_PORT ?? '5173'
const CA_PORT = process.env.CA_PORT ?? '5000'
const SUITE_PORT = Number(process.env.SUITE_PORT ?? '4000')
const COPILOTKIT_PORT = process.env.COPILOTKIT_PORT ?? '4100'

const BASE_PATH = (process.env.VITE_BASE_PATH ?? '/app').replace(/\/$/, '')

export default defineConfig({
  base: `${BASE_PATH}/`,
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  server: {
    port: SUITE_PORT,
    proxy: {
      '/api/copilotkit': {
        target: `http://localhost:${COPILOTKIT_PORT}`,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api\/copilotkit/, '/copilotkit'),
      },
      '/api/kg': {
        target: `http://localhost:${KG_BACKEND_PORT}`,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api\/kg/, '/api'),
      },
      '/api/ca': {
        target: `http://localhost:${CA_PORT}`,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api\/ca/, '/app/api'),
      },
      '/ws/kg': {
        target: `ws://localhost:${KG_BACKEND_PORT}`,
        ws: true,
        rewrite: (p) => p.replace(/^\/ws\/kg/, '/ws'),
      },
    },
  },
})
