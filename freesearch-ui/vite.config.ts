import path from "node:path"
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import babel from '@rolldown/plugin-babel'
import { defineConfig } from 'vite'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
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
    proxy: {
      "/search": "http://127.0.0.1:8001",
      "/fetch": "http://127.0.0.1:8001",
      "/stats": "http://127.0.0.1:8001",
      "/dashboard": "http://127.0.0.1:8001",
      "/api": "http://127.0.0.1:8001",
    },
  },
  preview: {
    proxy: {
      "/search": "http://127.0.0.1:8001",
      "/fetch": "http://127.0.0.1:8001",
      "/stats": "http://127.0.0.1:8001",
      "/dashboard": "http://127.0.0.1:8001",
      "/api": "http://127.0.0.1:8001",
    },
  },
})

