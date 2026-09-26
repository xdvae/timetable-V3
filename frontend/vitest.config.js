import path from 'node:path'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const dirname = path.dirname(fileURLToPath(import.meta.url))

// Test-only config (Phase 6P.4). Kept separate from vite.config.js so the
// dev/prod pipeline is untouched: plain react transform (no tailwind scan,
// no compiler preset) plus a single forks worker, because parallel jsdom
// workers exceed the startup budget on small machines.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(dirname, './src'),
    },
  },
  test: {
    pool: "forks",
    forks: { singleFork: true, isolate: true },
  },
})
