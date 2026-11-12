import path from "node:path"
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import babel from '@rolldown/plugin-babel'
import { defineConfig, loadEnv } from 'vite'
import tailwindcss from '@tailwindcss/vite'

/** Backend origin used by the dev/preview proxy when none is configured. */
const DEFAULT_BACKEND_URL = "http://127.0.0.1:8001"

/**
 * Proxy entries for one backend origin. Provider-querying routes plus the
 * monitoring, control-plane, trace read, account, and role APIs all live on the
 * API server. The account prefixes keep the browser on one origin, so the
 * refresh cookie and the `X-Polyweb-Client` marker reach the backend
 * unchanged.
 */
function proxyFor(backendUrl: string) {
  return {
    "/search": backendUrl,
    "/fetch": backendUrl,
    "/stats": backendUrl,
    "/dashboard": backendUrl,
    "/api": backendUrl,
    "/auth": backendUrl,
    "/users": backendUrl,
  }
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const rootDir = path.resolve(import.meta.dirname, "..")
  // Shell environment wins over .env files, so a session can point the UI at
  // a different backend or port without changing committed defaults.
  const env = {
    ...loadEnv(mode, rootDir, ["VITE_", "POLYWEB_"]),
    ...loadEnv(mode, process.cwd(), ["VITE_", "POLYWEB_"]),
    ...process.env,
  }
  const backendPort = env.POLYWEB_API_PORT || "8001"
  const backendUrl =
    env.VITE_BACKEND_URL ||
    (env.POLYWEB_API_PORT ? `http://127.0.0.1:${backendPort}` : DEFAULT_BACKEND_URL)
  const port = Number(env.VITE_PORT || 5174)

  return {
    build: {
      license: { fileName: "THIRD_PARTY_LICENSES.md" },
    },
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
      port,
      proxy: proxyFor(backendUrl),
    },
    preview: {
      port,
      proxy: proxyFor(backendUrl),
    },
  }
})
