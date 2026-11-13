import fs from "node:fs";
import path from "node:path";
import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";

// Default dev-server port. No worktree uses this port today:
// UI uses 5174-5178, landing uses 5274, backend/MCP use 8000+.
const DEFAULT_DOCS_PORT = 5284;

// Read one value from the repo-root .env file. Shell environment wins:
// export POLYWEB_DOCS_PORT=5285 to run a second copy in another worktree.
function docsPort() {
  if (process.env.POLYWEB_DOCS_PORT) {
    return Number(process.env.POLYWEB_DOCS_PORT);
  }
  try {
    const rootEnv = fs.readFileSync(
      path.resolve(import.meta.dirname, "..", ".env"),
      "utf8",
    );
    const match = /^POLYWEB_DOCS_PORT\s*=\s*(\d+)/m.exec(rootEnv);
    if (match) {
      return Number(match[1]);
    }
  } catch {
    // No root .env file: use the default port.
  }
  return DEFAULT_DOCS_PORT;
}

// https://starlight.astro.build/reference/configuration/
export default defineConfig({
  site: "https://docs.polyweb.dev",
  vite: {
    build: {
      license: { fileName: "THIRD_PARTY_LICENSES.md" },
    },
  },
  server: { host: "127.0.0.1", port: docsPort() },
  preview: { host: "127.0.0.1", port: docsPort() },
  integrations: [
    starlight({
      title: "Polyweb",
      description:
        "Install Polyweb with Docker, connect an AI agent, and call search and fetch from one place.",
      logo: {
        src: "./src/assets/logo.webp",
        alt: "Polyweb",
      },
      favicon: "/favicon.png",
      social: [
        {
          icon: "github",
          label: "GitHub",
          href: "https://github.com/polyweb-dev/polyweb-mcp",
        },
      ],
      components: {
        Hero: "./src/components/Hero.astro",
      },
      sidebar: [
        {
          label: "Get started",
          items: [
            { label: "Quick start (Docker)", slug: "quick-start" },
            { label: "Your first search", slug: "guides/first-search" },
            { label: "Manual setup", slug: "setup/manual" },
            { label: "Configuration", slug: "setup/configuration" },
            { label: "Back up and upgrade", slug: "setup/backup-and-upgrade" },
            { label: "Admin accounts", slug: "setup/admin-accounts" },
          ],
        },
        {
          label: "Concepts",
          items: [
            { label: "Projects and roles", slug: "concepts/projects-and-roles" },
            { label: "Authentication and keys", slug: "concepts/authentication" },
            { label: "Routing", slug: "concepts/routing" },
            { label: "Rate limits and budgets", slug: "concepts/limits-and-budgets" },
          ],
        },
        {
          label: "Dashboard",
          items: [
            { label: "Dashboard tour", slug: "dashboard/overview" },
            { label: "Sign in and account", slug: "dashboard/account" },
            { label: "Provider keys and pools", slug: "dashboard/provider-keys" },
            { label: "Project providers", slug: "dashboard/project-providers" },
            { label: "Project API keys", slug: "dashboard/api-keys" },
            { label: "Project settings and members", slug: "dashboard/project" },
            { label: "Playground", slug: "dashboard/playground" },
            { label: "Activity and traces", slug: "dashboard/activity" },
            { label: "Usage", slug: "dashboard/usage" },
            { label: "System providers and quotas", slug: "dashboard/system-admin" },
          ],
        },
        {
          label: "MCP server",
          items: [
            { label: "Connect an agent", slug: "mcp/connect" },
            { label: "search tool", slug: "mcp/search-tool" },
            { label: "fetch tool", slug: "mcp/fetch-tool" },
          ],
        },
        {
          label: "REST API",
          items: [
            { label: "Overview and auth", slug: "api/overview" },
            { label: "POST /search", slug: "api/search" },
            { label: "POST /fetch", slug: "api/fetch" },
            { label: "Examples", slug: "api/examples" },
          ],
        },
        {
          label: "Providers",
          items: [
            { label: "Provider overview", slug: "providers/overview" },
            { label: "Provider reference", slug: "providers/reference" },
            { label: "Request options", slug: "providers/request-options" },
          ],
        },
        {
          label: "Reference",
          items: [
            { label: "Troubleshooting", slug: "reference/troubleshooting" },
            { label: "Security", slug: "reference/security" },
            { label: "Contributing", slug: "reference/contributing" },
          ],
        },
      ],
    }),
  ],
});
