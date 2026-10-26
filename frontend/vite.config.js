import path from 'node:path'
import { fileURLToPath } from 'node:url'
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import babel from '@rolldown/plugin-babel'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

const dirname = path.dirname(fileURLToPath(import.meta.url))

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    babel({ presets: [reactCompilerPreset()] }),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(dirname, './src'),
    },
  },
  server: {
    // Dev-only proxy so the SPA can use same-origin /api calls while the
    // Flask backend runs on :5050. Production serves same-origin: no CORS.
    // /export and /import/sample are file downloads served by Flask; without
    // these entries the dev server answered them with the SPA's index.html.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5050',
        changeOrigin: true,
      },
      '/export': {
        target: 'http://127.0.0.1:5050',
        changeOrigin: true,
      },
      '/import/sample': {
        target: 'http://127.0.0.1:5050',
        changeOrigin: true,
      },
    },
  },
})
