import path from "node:path"
import react from "@vitejs/plugin-react"
import { defineConfig, loadEnv } from "vite"

export default defineConfig(({ mode }) => {
  const env = {
    ...loadEnv(mode, path.resolve(import.meta.dirname, ".."), [
      "POLYWEB_LANDING_",
    ]),
    ...process.env,
  }
  const port = Number(env.POLYWEB_LANDING_PORT || 5274)

  return {
    build: {
      license: { fileName: "THIRD_PARTY_LICENSES.md" },
    },
    plugins: [react()],
    server: { port },
    preview: { port },
  }
})
