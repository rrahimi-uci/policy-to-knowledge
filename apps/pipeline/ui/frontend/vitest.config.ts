import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['allure-vitest/setup', './src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    reporters: [
      'default',
      ['allure-vitest/reporter', { resultsDir: 'allure-results' }],
    ],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'lcov'],
      reportsDirectory: 'coverage',
      // Measure the unit-testable logic layer. Pages, the multi-run pipeline
      // hook, websocket/streaming/graph components and other data-bound UI are
      // exercised by the Playwright e2e suite, not unit tests.
      include: [
        'src/lib/**/*.{ts,tsx}',
        'src/hooks/useTheme.tsx',
        'src/components/ErrorBoundary.tsx',
      ],
      exclude: ['src/**/*.{test,spec}.{ts,tsx}'],
    },
  },
})
