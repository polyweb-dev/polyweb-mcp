import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import type { RecordedRequest } from "@/test/fetchMock"
import { ProjectScopeProvider, ProjectsProvider } from "@/domains/projects"
import type { ProjectApiKey } from "@/domains/projects"
import {
  PROJECT_ADMIN_PERMISSIONS,
  PROJECT_ALPHA_ID,
  apiKeyFixture,
  projectFixture,
} from "@/test/accessFixtures"
import { ProjectApiKeysPage } from "./ProjectApiKeysPage"

const ACCOUNT = "acc"
const CREATOR = "11111111-1111-4111-8111-111111111111"
/** Opaque stand-in for a one-time key; it is not a real credential. */
const ONE_TIME_VALUE = "fs_live_test-only-opaque-value"

interface StubOptions {
  permissions?: readonly string[]
  status?: "active" | "archived"
  keys?: ProjectApiKey[]
  onMutation?: (req: RecordedRequest) => Response | null
}

function installKeysStub(options: StubOptions = {}) {
  const keys = [...(options.keys ?? [])]
  const permissions = options.permissions ?? PROJECT_ADMIN_PERMISSIONS
  const base = `/api/v1/projects/${PROJECT_ALPHA_ID}`
  return installFetchStub((req) => {
    if (req.url === "/api/v1/system/access") return ok({ rollout_state: "preview", permissions: [] })
    if (req.url === "/api/v1/projects?include_archived=true") {
      return ok([projectFixture({ status: options.status ?? "active" })])
    }
    if (req.url === `${base}/access`) {
      return ok({ project_id: PROJECT_ALPHA_ID, permissions, roles: [], policy_revision: 1 })
    }
    if (req.url === `${base}/members`) {
      return ok([{ project_id: PROJECT_ALPHA_ID, user_id: CREATOR, email: "lead@example.com", status: "active", roles: ["project_admin"], role: "admin", permissions: 15, provider_owner: false, version: 1 }])
    }
    if (req.url === `${base}/api-keys` && req.method === "GET") return ok(keys)
    const override = options.onMutation?.(req)
    if (override) return override
    if (req.url === `${base}/api-keys` && req.method === "POST") {
      const body = req.body as { label: string; scopes: string[]; expires_at?: string | null }
      const created = apiKeyFixture({
        id: `key-${keys.length + 1}`,
        label: body.label,
        scopes: body.scopes,
        created_at: "2026-10-30T00:00:00Z",
        expires_at: body.expires_at === undefined ? "2027-01-28T00:00:00Z" : body.expires_at,
        created_by: CREATOR,
      })
      keys.push(created)
      return ok({ ...created, key: ONE_TIME_VALUE }, 201)
    }
    const rotate = new RegExp(`^${base}/api-keys/([^/]+)/rotate$`).exec(req.url)
    if (rotate !== null && req.method === "POST") {
      const replacement = apiKeyFixture({ id: "rotated", rotated_from_id: rotate[1] ?? null, created_at: "2026-10-31T00:00:00Z" })
      keys.push(replacement)
      return ok({ ...replacement, key: ONE_TIME_VALUE }, 201)
    }
    const revoke = new RegExp(`^${base}/api-keys/([^/]+)$`).exec(req.url)
    if (revoke !== null && req.method === "DELETE") {
      const index = keys.findIndex((key) => key.id === revoke[1])
      const current = keys[index]
      if (current) keys[index] = { ...current, status: "revoked", revoked_at: "2026-10-31T00:00:00Z" }
      return new Response(null, { status: 204 })
    }
    return err(404, null)
  })
}

function renderPage() {
  return render(
    <MemoryRouter>
      <ProjectsProvider accountId={ACCOUNT}>
        <ProjectScopeProvider accountId={ACCOUNT} projectId={PROJECT_ALPHA_ID}>
          <ProjectApiKeysPage accountId={ACCOUNT} />
        </ProjectScopeProvider>
      </ProjectsProvider>
    </MemoryRouter>
  )
}

async function issueKey(user: ReturnType<typeof userEvent.setup>, label: string) {
  await user.type(await screen.findByLabelText("Label"), label)
  await user.click(screen.getByRole("button", { name: "Issue key" }))
}

/** Opens the `…` row menu of one key, then chooses one of its actions. */
async function chooseRowAction(
  user: ReturnType<typeof userEvent.setup>,
  keyLabel: string,
  action: "Rotate" | "Revoke"
) {
  await user.click(await screen.findByRole("button", { name: `Actions for ${keyLabel}` }))
  await user.click(screen.getByRole("button", { name: action }))
}

beforeEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("ProjectApiKeysPage issue and reveal", () => {
  it("renders the heading, the issue form defaults and the empty table", async () => {
    installKeysStub()
    renderPage()
    expect(await screen.findByRole("heading", { name: "API keys" })).toBeInTheDocument()
    const form = screen.getByRole("region", { name: "New API key" })
    expect(within(form).getByRole("checkbox", { name: "Search" })).toBeChecked()
    expect(within(form).getByRole("checkbox", { name: "Fetch" })).toBeChecked()
    const expiration = within(form).getByRole("group", { name: "Expiration" })
    expect(within(expiration).getByRole("button", { name: "90 days" })).toHaveAttribute("aria-pressed", "true")
    expect(within(expiration).getByRole("button", { name: "No expiration" })).toHaveAttribute("aria-pressed", "false")
    expect(await screen.findByRole("table", { name: "API keys" })).toBeInTheDocument()
  })

  it("issues a key with No expiration, reveals it once, and forgets it on Done", async () => {
    const stub = installKeysStub()
    const user = userEvent.setup()
    renderPage()

    await user.type(await screen.findByLabelText("Label"), "Nightly")
    await user.click(screen.getByRole("button", { name: "No expiration" }))
    await user.click(screen.getByRole("button", { name: "Issue key" }))

    const dialog = await screen.findByRole("dialog", { name: "Copy your new API key" })
    expect(within(dialog).getByText("This key is shown only once.")).toBeInTheDocument()
    expect(within(dialog).getByLabelText("API key")).toHaveValue(ONE_TIME_VALUE)
    expect(within(dialog).getByRole("button", { name: "Copy key" })).toBeInTheDocument()
    const post = stub.requests.find((req) => req.method === "POST")
    expect(post?.bodyText).toBe('{"label":"Nightly","scopes":["search.execute","fetch.execute"],"expires_at":null}')

    await user.click(within(dialog).getByRole("button", { name: "Done" }))
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Copy your new API key" })).toBeNull())
    const table = await screen.findByRole("table", { name: "API keys" })
    await waitFor(() => expect(within(table).getByText("Nightly")).toBeInTheDocument())
    expect(within(table).getByText("No expiration")).toBeInTheDocument()
    expect(document.body.textContent ?? "").not.toContain(ONE_TIME_VALUE)
    expect(document.body.innerHTML).not.toContain(ONE_TIME_VALUE)
    expect(JSON.stringify({ ...window.localStorage })).not.toContain(ONE_TIME_VALUE)
    expect(JSON.stringify({ ...window.sessionStorage })).not.toContain(ONE_TIME_VALUE)
    expect(screen.getByLabelText("Label")).toHaveValue("")
  })

  it("omits expires_at for the default lifetime and copies the key", async () => {
    const stub = installKeysStub()
    const writeText = vi.fn(async () => {})
    const user = userEvent.setup()
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true })
    renderPage()

    await issueKey(user, "Default")
    const dialog = await screen.findByRole("dialog", { name: "Copy your new API key" })
    const post = stub.requests.find((req) => req.method === "POST")
    expect(post?.body).toEqual({ label: "Default", scopes: ["search.execute", "fetch.execute"] })

    await user.click(within(dialog).getByRole("button", { name: "Copy key" }))
    expect(writeText).toHaveBeenCalledWith(ONE_TIME_VALUE)
    expect(await within(dialog).findByText("Copied to the clipboard.")).toBeInTheDocument()
  })

  it("disables a scope the caller lacks and issues only the held scope", async () => {
    const stub = installKeysStub({ permissions: ["project.read", "tokens.manage", "search.execute"] })
    const user = userEvent.setup()
    renderPage()

    const fetchBox = await screen.findByRole("checkbox", { name: "Fetch" })
    expect(fetchBox).toBeDisabled()
    expect(fetchBox).not.toBeChecked()
    await issueKey(user, "Search only")
    await screen.findByRole("dialog", { name: "Copy your new API key" })
    expect(stub.requests.find((req) => req.method === "POST")?.body).toMatchObject({ scopes: ["search.execute"] })
  })

  it("validates the label and the scopes without a request", async () => {
    const stub = installKeysStub()
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole("button", { name: "Issue key" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter a label for the key")
    await user.type(screen.getByLabelText("Label"), "x")
    await user.click(screen.getByRole("checkbox", { name: "Search" }))
    await user.click(screen.getByRole("checkbox", { name: "Fetch" }))
    await user.click(screen.getByRole("button", { name: "Issue key" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("Choose at least one scope")
    expect(stub.requests.filter((req) => req.method === "POST")).toHaveLength(0)
  })

  it("sends a custom date as a future timestamp and rejects a past one", async () => {
    const stub = installKeysStub()
    const user = userEvent.setup()
    renderPage()

    await user.type(await screen.findByLabelText("Label"), "Dated")
    await user.click(screen.getByRole("button", { name: "Custom date" }))
    const date = screen.getByLabelText("Expiration date")
    await user.type(date, "2000-01-01")
    await user.click(screen.getByRole("button", { name: "Issue key" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("Choose an expiration date in the future")

    await user.clear(date)
    await user.type(date, "2099-06-30")
    await user.click(screen.getByRole("button", { name: "Issue key" }))
    await screen.findByRole("dialog", { name: "Copy your new API key" })
    const body = stub.requests.find((req) => req.method === "POST")?.body as { expires_at: string }
    expect(Date.parse(body.expires_at)).toBeGreaterThan(Date.now())
  })
})

describe("ProjectApiKeysPage list", () => {
  it("lists keys newest first with creator email, never-used and status columns", async () => {
    installKeysStub({
      keys: [
        apiKeyFixture({ id: "old", label: "Old", created_at: "2026-09-01T00:00:00Z", status: "revoked", revoked_at: "2026-09-02T00:00:00Z" }),
        apiKeyFixture({ id: "new", label: "New", created_at: "2026-10-01T00:00:00Z", created_by: CREATOR }),
      ],
    })
    renderPage()

    const table = await screen.findByRole("table", { name: "API keys" })
    const headers = within(table).getAllByRole("columnheader").map((cell) => cell.textContent)
    expect(headers.slice(0, 6)).toEqual(["Key", "Scopes", "Created", "Expires", "Last used", "Status"])
    const rows = await within(table).findAllByRole("row")
    expect(rows[1]).toHaveTextContent("New")
    expect(rows[2]).toHaveTextContent("Old")
    await waitFor(() => expect(rows[1]).toHaveTextContent("lead@example.com"))
    expect(rows[1]).toHaveTextContent("Never")
    expect(rows[1]).toHaveTextContent("Active")
    expect(rows[2]).toHaveTextContent("Revoked")
    expect(within(table).queryByRole("button", { name: "Actions for Old" })).toBeNull()
    expect(within(table).getByRole("button", { name: "Actions for New" })).toBeInTheDocument()
  })

  it("shows a short creator id when members are not readable", async () => {
    const stub = installKeysStub({
      permissions: ["project.read", "tokens.manage", "search.execute"],
      keys: [apiKeyFixture({ created_by: CREATOR })],
    })
    renderPage()
    const table = await screen.findByRole("table", { name: "API keys" })
    expect(await within(table).findByText("11111111")).toBeInTheDocument()
    expect(stub.requestsTo(`/api/v1/projects/${PROJECT_ALPHA_ID}/members`)).toHaveLength(0)
  })
})

describe("ProjectApiKeysPage rotate and revoke", () => {
  it("rotates with the default 24-hour overlap and reveals the new key once", async () => {
    const stub = installKeysStub({ keys: [apiKeyFixture({ id: "k1", label: "CI runner" })] })
    const user = userEvent.setup()
    renderPage()

    await chooseRowAction(user, "CI runner", "Rotate")
    const dialog = await screen.findByRole("dialog", { name: "Rotate CI runner" })
    const overlap = within(dialog).getByLabelText("Old key stays valid for")
    expect(overlap).toHaveTextContent("24 hours")
    expect(within(dialog).getByRole("button", { name: "Keep current" })).toHaveAttribute("aria-pressed", "true")
    await user.click(within(dialog).getByRole("button", { name: "Rotate key" }))

    const reveal = await screen.findByRole("dialog", { name: "Copy your new API key" })
    expect(within(reveal).getByLabelText("API key")).toHaveValue(ONE_TIME_VALUE)
    const post = stub.requests.find((req) => req.url.endsWith("/api-keys/k1/rotate"))
    expect(post?.body).toEqual({ overlap_seconds: 86_400 })
    expect(screen.queryByRole("dialog", { name: "Rotate CI runner" })).toBeNull()
  })

  it("rotates with an immediate revoke and No expiration", async () => {
    const stub = installKeysStub({ keys: [apiKeyFixture({ id: "k1", label: "CI runner" })] })
    const user = userEvent.setup()
    renderPage()

    await chooseRowAction(user, "CI runner", "Rotate")
    const dialog = await screen.findByRole("dialog", { name: "Rotate CI runner" })
    await user.click(within(dialog).getByLabelText("Old key stays valid for"))
    await user.click(within(dialog).getByRole("option", { name: "Revoke old key now" }))
    await user.click(within(dialog).getByRole("button", { name: "No expiration" }))
    await user.click(within(dialog).getByRole("button", { name: "Rotate key" }))
    await screen.findByRole("dialog", { name: "Copy your new API key" })
    expect(stub.requests.find((req) => req.url.endsWith("/rotate"))?.body).toEqual({
      overlap_seconds: 0,
      expires_at: null,
    })
  })

  it("shows the inactive-key conflict inside the rotate dialog", async () => {
    installKeysStub({
      keys: [apiKeyFixture({ id: "k1", label: "CI runner" })],
      onMutation: (req) =>
        req.url.endsWith("/rotate") ? err(409, { detail: { code: "API_KEY_INACTIVE", message: "x" } }) : null,
    })
    const user = userEvent.setup()
    renderPage()

    await chooseRowAction(user, "CI runner", "Rotate")
    const dialog = await screen.findByRole("dialog", { name: "Rotate CI runner" })
    await user.click(within(dialog).getByRole("button", { name: "Rotate key" }))
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("This key is no longer active.")
    expect(screen.queryByRole("dialog", { name: "Copy your new API key" })).toBeNull()
  })

  it("revokes only after the confirmation dialog", async () => {
    const stub = installKeysStub({ keys: [apiKeyFixture({ id: "k1", label: "CI runner" })] })
    const user = userEvent.setup()
    renderPage()

    await chooseRowAction(user, "CI runner", "Revoke")
    expect(stub.requests.filter((req) => req.method === "DELETE")).toHaveLength(0)
    const dialog = await screen.findByRole("dialog", { name: "Revoke CI runner" })
    expect(dialog).toHaveTextContent("Programs that use this key stop working at once. You cannot undo this change")
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }))
    await waitFor(() => expect(screen.queryByRole("button", { name: "Revoke key" })).toBeNull())

    await chooseRowAction(user, "CI runner", "Revoke")
    await user.click(await screen.findByRole("button", { name: "Revoke key" }))
    const table = await screen.findByRole("table", { name: "API keys" })
    await waitFor(() => expect(within(table).getByText("Revoked")).toBeInTheDocument())
    expect(stub.requests.filter((req) => req.method === "DELETE").map((req) => req.url)).toEqual([
      `/api/v1/projects/${PROJECT_ALPHA_ID}/api-keys/k1`,
    ])
  })

  it("maps a 403 to the permission copy and refreshes the access", async () => {
    const stub = installKeysStub({
      keys: [apiKeyFixture({ id: "k1", label: "CI runner" })],
      onMutation: (req) => (req.method === "DELETE" ? err(403, null) : null),
    })
    const user = userEvent.setup()
    renderPage()

    await chooseRowAction(user, "CI runner", "Revoke")
    const accessReads = stub.requestsTo(`/api/v1/projects/${PROJECT_ALPHA_ID}/access`).length
    await user.click(await screen.findByRole("button", { name: "Revoke key" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("You no longer have permission for this action.")
    await waitFor(() =>
      expect(stub.requestsTo(`/api/v1/projects/${PROJECT_ALPHA_ID}/access`).length).toBeGreaterThan(accessReads)
    )
  })

  it("maps the archived-project conflict of an issue", async () => {
    installKeysStub({
      onMutation: (req) =>
        req.method === "POST" ? err(409, { detail: { code: "PROJECT_ARCHIVED", message: "x" } }) : null,
    })
    const user = userEvent.setup()
    renderPage()
    await issueKey(user, "Late")
    expect(await screen.findByRole("alert")).toHaveTextContent("An archived project cannot issue or rotate keys.")
  })
})

describe("ProjectApiKeysPage archived project", () => {
  it("hides issue and rotate, keeps revoke, and explains why", async () => {
    const user = userEvent.setup()
    installKeysStub({ status: "archived", keys: [apiKeyFixture({ id: "k1", label: "CI runner" })] })
    renderPage()

    expect(
      await screen.findByText("This project is archived. Its keys can be revoked but not issued or rotated.")
    ).toBeInTheDocument()
    expect(screen.queryByRole("region", { name: "New API key" })).toBeNull()

    const trigger = await screen.findByRole("button", { name: "Actions for CI runner" })
    await user.click(trigger)
    expect(screen.queryByRole("button", { name: "Rotate" })).toBeNull()
    expect(screen.getByRole("button", { name: "Revoke" })).toBeInTheDocument()
  })
})
