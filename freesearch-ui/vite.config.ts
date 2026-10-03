import path from "node:path"
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import babel from '@rolldown/plugin-babel'
import { defineConfig, loadEnv } from 'vite'
import tailwindcss from '@tailwindcss/vite'

/** Backend origin used by the dev/preview proxy when none is configured. */
const DEFAULT_BACKEND_URL = "http://127.0.0.1:8001"

/**
 * Proxy entries for one backend origin. Provider-querying routes plus the
 * monitoring, control-plane, and trace read APIs all live on the API server.
 */
function proxyFor(backendUrl: string) {
  return {
    "/search": backendUrl,
    "/fetch": backendUrl,
    "/stats": backendUrl,
    "/dashboard": backendUrl,
    "/api": backendUrl,
  }
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Shell environment wins over .env files, so a session can point the UI at
  // a different backend (e.g. 8003) without changing the committed default.
  const env = { ...loadEnv(mode, process.cwd(), "VITE_"), ...process.env }
  const backendUrl = env.VITE_BACKEND_URL || DEFAULT_BACKEND_URL

  return {
    plugins: [
      react(),
      babel({ presets: [reactCompilerPreset()] }),
      tailwindcss(),
    ],
    resolve: {
      alias: {
        "@": path.resolve(import.meta.dirname, "./src"),
      },
    },
    server: {
      proxy: proxyFor(backendUrl),
    },
    preview: {
      proxy: proxyFor(backendUrl),
    },
  }
})
