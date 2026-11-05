import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { err, ok } from "@/test/fetchMock"
import type { RecordedRequest } from "@/test/fetchMock"
import { PROJECT_ALPHA_ID, PROJECT_MEMBER_PERMISSIONS } from "@/test/accessFixtures"
import { FAKE_PROVIDER_KEY, installWorkspaceStub, leakedAnywhere, renderInProject } from "@/test/workspaceHarness"
import { ProjectProvidersPage } from "./ProjectProvidersPage"

const BASE = `/api/v1/projects/${PROJECT_ALPHA_ID}`
/** The write-only field; the auth mode radio shares the "API key" name. */
const SECRET = { selector: "input[type='password']" }

function providerView(overrides: { bindings?: unknown[]; allocations?: unknown[]; killSwitch?: boolean } = {}) {
  return {
    project_id: PROJECT_ALPHA_ID,
    providers: [
      {
        provider_type: "tavily",
        capability: ["search", "fetch"],
        kill_switch: overrides.killSwitch ?? false,
        system_enabled_operations: ["search", "fetch"],
        available: true,
        enabled: true,
        effective_operations: ["search"],
        credentials: [
          { id: "own", label: "Team Tavily", owner_scope: "project", auth_mode: "api_key", status: "active", health_status: "healthy", granted_operations: ["search", "fetch"], supported_operations: ["search", "fetch"], pools: [] },
          { id: "shared", label: "Shared Tavily", owner_scope: "system", auth_mode: "api_key", status: "active", health_status: null, granted_operations: ["search"], supported_operations: ["search", "fetch"], pools: [{ operation_scope: "search", pool_id: "pool-1", label: "Tavily account", upstream_scope: "account", status: "active" }] },
        ],
        bindings: overrides.bindings ?? [
          { id: "b1", credential_id: "own", route_label: "primary", priority: 100, enabled_operations: ["search"], effective_operations: ["search"] },
        ],
      },
      {
        provider_type: "parallel",
        capability: ["search", "fetch"],
        kill_switch: false,
        system_enabled_operations: ["search"],
        available: true,
        enabled: false,
        effective_operations: [],
        credentials: [
          { id: "par", label: "Team Parallel", owner_scope: "project", auth_mode: "oauth", status: "active", granted_operations: ["search"], supported_operations: ["search"], pools: [] },
        ],
        bindings: [],
      },
    ],
    allocations: overrides.allocations ?? [],
  }
}

const PROJECT_CREDENTIALS = [
  { id: "own", provider_type: "tavily", owner_scope: "project", label: "Team Tavily", auth_mode: "api_key", status: "active", permitted_operations: ["search", "fetch"], can_manage: true, generation: 2 },
  { id: "shared", provider_type: "tavily", owner_scope: "system", label: "Shared Tavily", auth_mode: "api_key", status: "active", permitted_operations: ["search"], can_manage: false, generation: null },
  { id: "par", provider_type: "parallel", owner_scope: "project", label: "Team Parallel", auth_mode: "oauth", status: "active", permitted_operations: ["search"], can_manage: true, generation: 1 },
]

interface StubOptions {
  permissions?: readonly string[]
  view?: ReturnType<typeof providerView>
  onMutation?: (req: RecordedRequest) => Response | null
}

function installProvidersStub(options: StubOptions = {}) {
  return installWorkspaceStub(
    (req) => {
      if (req.method === "GET" && req.url === `${BASE}/providers`) return ok(options.view ?? providerView())
      if (req.method === "GET" && req.url === `${BASE}/credentials`) return ok(PROJECT_CREDENTIALS)
      const override = options.onMutation?.(req)
      if (override) return override
      if (req.method === "POST" && req.url === `${BASE}/credentials`) {
        const body = req.body as { label: string; provider_type: string; auth_mode: string }
        return ok({ id: "new", provider_type: body.provider_type, owner_scope: "project", label: body.label, auth_mode: body.auth_mode, status: "active", permitted_operations: [], can_manage: true, generation: 1 }, 201)
      }
      if (req.method === "POST" && req.url.endsWith("/rotate")) return ok({ ...PROJECT_CREDENTIALS[0], generation: 3 })
      if (req.method === "POST" && req.url === `${BASE}/bindings`) {
        return ok({ id: "b2", project_id: PROJECT_ALPHA_ID, credential_id: "own", route_label: "backup", enabled_operations: [], priority: 100, version: 1 }, 201)
      }
      if (req.method === "PATCH") return ok({ id: "b1", project_id: PROJECT_ALPHA_ID, credential_id: "own", route_label: "primary", enabled_operations: ["search", "fetch"], priority: 100, version: 2 })
      if (req.method === "DELETE") return new Response(null, { status: 204 })
      return err(404, null)
    },
    { projectPermissions: options.permissions }
  )
}

beforeEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
})
afterEach(() => vi.unstubAllGlobals())

describe("ProjectProvidersPage view", () => {
  it("shows provider sections with credentials, bindings and effective operations", async () => {
    installProvidersStub()
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    const tavily = await screen.findByRole("region", { name: "Tavily provider" })
    expect(tavily).toHaveAttribute("data-testid", "provider-type-tavily")
    expect(within(tavily).getAllByText("search").length).toBeGreaterThan(0)
    expect(screen.getByRole("region", { name: "Parallel provider" })).toHaveTextContent("—")
    const credentials = within(tavily).getByRole("table", { name: "Tavily credentials" })
    expect(within(credentials).getByText("Project")).toBeInTheDocument()
    expect(within(credentials).getByText("System (granted)")).toBeInTheDocument()
    const bindings = within(tavily).getByRole("table", { name: "Tavily bindings" })
    expect(within(bindings).getByRole("switch", { name: "Enable search for primary" })).toBeChecked()
    expect(within(bindings).getByRole("switch", { name: "Enable fetch for primary" })).not.toBeChecked()
    expect(screen.getByRole("heading", { name: "Providers" })).toBeInTheDocument()
  })

  it("shows the kill switch badge", async () => {
    installProvidersStub({ view: providerView({ killSwitch: true }) })
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    const tavily = await screen.findByRole("region", { name: "Tavily provider" })
    expect(within(tavily).getByText("Disabled by system")).toBeInTheDocument()
  })

  it("is read-only without providers.configure and credentials.manage_private", async () => {
    installProvidersStub({ permissions: PROJECT_MEMBER_PERMISSIONS })
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    const tavily = await screen.findByRole("region", { name: "Tavily provider" })
    expect(await screen.findByText("You can view providers. Ask a project administrator to change them.")).toBeInTheDocument()
    expect(within(tavily).getByRole("switch", { name: "Enable search for primary" })).toBeDisabled()
    expect(within(tavily).queryByRole("button", { name: "Add binding" })).toBeNull()
    expect(within(tavily).queryByRole("button", { name: "Remove binding primary" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Add provider key" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Rotate key Team Tavily" })).toBeNull()
  })

  it("shows allocations read-only with the shared explanation", async () => {
    installProvidersStub({
      view: providerView({
        allocations: [{ project_id: PROJECT_ALPHA_ID, pool_id: "pool-1", operation_scope: "search", base_rate: 10, rate_window_seconds: 60, borrow_enabled: false, max_rate: null, effective_max_rate: 10, weight: 1, best_effort: false, version: 1 }],
      }),
    })
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    const section = await screen.findByRole("region", { name: "Capacity allocations" })
    expect(within(section).getByText(/Tavily account/)).toBeInTheDocument()
    expect(within(section).getByTestId("allocation-explanation")).toHaveTextContent("Up to 10 per minute. Unused capacity of other projects is not lent.")
    expect(within(section).getByText("Set by a system administrator.")).toBeInTheDocument()
    expect(within(section).queryByRole("button")).toBeNull()
  })

  it("shows the empty allocation state", async () => {
    installProvidersStub()
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    expect(await screen.findByText("No shared-pool allocations are set for this project.")).toBeInTheDocument()
  })
})

describe("ProjectProvidersPage bindings", () => {
  it("creates a binding that starts turned off", async () => {
    const stub = installProvidersStub()
    const user = userEvent.setup()
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    const tavily = await screen.findByRole("region", { name: "Tavily provider" })
    await user.click(within(tavily).getByRole("button", { name: "Add binding" }))
    expect(within(tavily).getByLabelText("Priority")).toHaveValue(100)
    await user.selectOptions(within(tavily).getByLabelText("Credential"), "shared")
    await user.type(within(tavily).getByLabelText("Route label"), "backup")
    await user.click(within(tavily).getByRole("button", { name: "Create binding" }))
    expect(await screen.findByText("New bindings start turned off. Turn on search or fetch to use it.")).toBeInTheDocument()
    const post = stub.requests.find((req) => req.method === "POST" && req.url === `${BASE}/bindings`)
    expect(post?.body).toEqual({ credential_id: "shared", route_label: "backup", priority: 100 })
  })

  it("toggles one operation and removes a binding", async () => {
    const stub = installProvidersStub()
    const user = userEvent.setup()
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    await user.click(await screen.findByRole("switch", { name: "Enable fetch for primary" }))
    await waitFor(() => expect(stub.requests.find((req) => req.method === "PATCH")?.body).toEqual({ enabled_operations: ["search", "fetch"] }))
    await user.click(screen.getByRole("button", { name: "Remove binding primary" }))
    const dialog = await screen.findByRole("dialog")
    await user.click(within(dialog).getByRole("button", { name: "Remove binding" }))
    await waitFor(() => expect(stub.requests.find((req) => req.method === "DELETE")?.url).toBe(`${BASE}/bindings/b1`))
  })
})

describe("ProjectProvidersPage private keys", () => {
  it("saves a key, shows only metadata, and keeps the key out of DOM, storage and URL", async () => {
    const stub = installProvidersStub()
    const user = userEvent.setup()
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    await user.click(await screen.findByRole("button", { name: "Add provider key" }))
    const dialog = await screen.findByRole("dialog", { name: "Add provider key" })
    await user.selectOptions(within(dialog).getByLabelText("Provider"), "tavily")
    await user.type(within(dialog).getByLabelText("Label"), "Nightly key")
    const secret = within(dialog).getByLabelText("API key", SECRET)
    expect(secret).toHaveAttribute("type", "password")
    expect(secret).toHaveAttribute("autocomplete", "off")
    await user.type(secret, FAKE_PROVIDER_KEY)
    await user.click(within(dialog).getByRole("button", { name: "Save key" }))
    expect(await screen.findByText("Key saved for Nightly key.")).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Add provider key" })).toBeNull())
    const post = stub.requests.find((req) => req.method === "POST" && req.url === `${BASE}/credentials`)
    expect(post?.body).toEqual({ provider_type: "tavily", label: "Nightly key", auth_mode: "api_key", secret: FAKE_PROVIDER_KEY })
    expect(leakedAnywhere(FAKE_PROVIDER_KEY)).toEqual([])
  })

  it("clears the key after a failed save and shows no server detail", async () => {
    installProvidersStub({
      onMutation: (req) => (req.method === "POST" && req.url === `${BASE}/credentials` ? err(422, { detail: [{ loc: ["body", "secret"], msg: FAKE_PROVIDER_KEY }] }) : null),
    })
    const user = userEvent.setup()
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    await user.click(await screen.findByRole("button", { name: "Add provider key" }))
    const dialog = await screen.findByRole("dialog", { name: "Add provider key" })
    await user.type(within(dialog).getByLabelText("Label"), "Bad key")
    await user.type(within(dialog).getByLabelText("API key", SECRET), FAKE_PROVIDER_KEY)
    await user.click(within(dialog).getByRole("button", { name: "Save key" }))
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("The key could not be saved.")
    expect(within(dialog).getByLabelText("API key", SECRET)).toHaveValue("")
    expect(leakedAnywhere(FAKE_PROVIDER_KEY)).toEqual([])
  })

  it("drops a typed key on cancel", async () => {
    installProvidersStub()
    const user = userEvent.setup()
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    await user.click(await screen.findByRole("button", { name: "Add provider key" }))
    const dialog = await screen.findByRole("dialog", { name: "Add provider key" })
    await user.type(within(dialog).getByLabelText("API key", SECRET), FAKE_PROVIDER_KEY)
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }))
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Add provider key" })).toBeNull())
    expect(leakedAnywhere(FAKE_PROVIDER_KEY)).toEqual([])
    await user.click(screen.getByRole("button", { name: "Add provider key" }))
    expect(await screen.findByLabelText("API key", SECRET)).toHaveValue("")
  })

  it("offers OAuth only for Parallel and then sends no secret", async () => {
    const stub = installProvidersStub()
    const user = userEvent.setup()
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    await user.click(await screen.findByRole("button", { name: "Add provider key" }))
    const dialog = await screen.findByRole("dialog", { name: "Add provider key" })
    await user.selectOptions(within(dialog).getByLabelText("Provider"), "tavily")
    expect(within(dialog).queryByRole("radio", { name: "OAuth" })).toBeNull()
    await user.selectOptions(within(dialog).getByLabelText("Provider"), "parallel")
    await user.click(within(dialog).getByRole("radio", { name: "OAuth" }))
    expect(within(dialog).queryByLabelText("API key", SECRET)).toBeNull()
    await user.type(within(dialog).getByLabelText("Label"), "Par")
    await user.click(within(dialog).getByRole("button", { name: "Save key" }))
    await screen.findByText("Key saved for Par.")
    expect(stub.requests.find((req) => req.method === "POST" && req.url === `${BASE}/credentials`)?.body).toEqual({ provider_type: "parallel", label: "Par", auth_mode: "oauth" })
  })

  it("rotates at the expected generation and maps a 409", async () => {
    let conflict = true
    const stub = installProvidersStub({
      onMutation: (req) => {
        if (!req.url.endsWith("/rotate") || !conflict) return null
        conflict = false
        return err(409, { detail: { code: "CREDENTIAL_GENERATION_CONFLICT", message: "stale" } })
      },
    })
    const user = userEvent.setup()
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    await user.click(await screen.findByRole("button", { name: "Rotate key Team Tavily" }))
    const dialog = await screen.findByRole("dialog", { name: "Rotate Team Tavily" })
    await user.type(within(dialog).getByLabelText("New API key"), FAKE_PROVIDER_KEY)
    await user.click(within(dialog).getByRole("button", { name: "Rotate key" }))
    expect(await within(dialog).findByText("This key changed since you opened it. Reload and try again.")).toBeInTheDocument()
    expect(within(dialog).getByLabelText("New API key")).toHaveValue("")
    const rotate = stub.requests.find((req) => req.url === `${BASE}/credentials/own/rotate`)
    expect(rotate?.body).toEqual({ expected_generation: 2, secret: FAKE_PROVIDER_KEY })

    await user.type(within(dialog).getByLabelText("New API key"), FAKE_PROVIDER_KEY)
    await user.click(within(dialog).getByRole("button", { name: "Rotate key" }))
    expect(await screen.findByText("Key saved for Team Tavily.")).toBeInTheDocument()
    expect(leakedAnywhere(FAKE_PROVIDER_KEY)).toEqual([])
  })

  it("offers actions only on manageable rows and deletes after confirmation", async () => {
    const stub = installProvidersStub()
    const user = userEvent.setup()
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    expect(await screen.findByRole("button", { name: "Delete key Team Tavily" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Delete key Shared Tavily" })).toBeNull()
    expect(screen.getByRole("button", { name: "Connect Team Parallel" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Disconnect Team Parallel" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Rotate key Team Parallel" })).toBeNull()
    await user.click(screen.getByRole("button", { name: "Delete key Team Tavily" }))
    const confirm = await screen.findByRole("dialog", { name: "Delete Team Tavily" })
    await user.click(within(confirm).getByRole("button", { name: "Delete key" }))
    await waitFor(() => expect(stub.requests.find((req) => req.method === "DELETE")?.url).toBe(`${BASE}/credentials/own`))
  })

  it("connects OAuth on the project credential base", async () => {
    const stub = installProvidersStub({
      onMutation: (req) =>
        req.url === `${BASE}/credentials/par/oauth/device`
          ? ok({ user_code: "WDJB-MJHT", verification_uri: "https://auth.example.test/device", interval: 5, expires_in: 600 }, 201)
          : null,
    })
    const user = userEvent.setup()
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    await user.click(await screen.findByRole("button", { name: "Connect Team Parallel" }))
    const dialog = await screen.findByRole("dialog", { name: "Connect Parallel" })
    expect(await within(dialog).findByTestId("oauth-user-code")).toHaveTextContent("WDJB-MJHT")
    expect(stub.requests.some((req) => req.url === `${BASE}/credentials/par/oauth/device`)).toBe(true)
  })
})
