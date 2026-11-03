import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { err, ok } from "@/test/fetchMock"
import { PROJECT_ALPHA_ID, PROJECT_BETA_ID, projectFixture } from "@/test/accessFixtures"
import { FAKE_PROVIDER_KEY, installWorkspaceStub, leakedAnywhere, renderInWorkspace } from "@/test/workspaceHarness"
import { SystemCredentialsPage } from "./SystemCredentialsPage"

const SECRET = { selector: "input[type='password']" }
const ROWS = [
  { id: "c1", provider_type: "brave", owner_scope: "system", label: "Shared Brave", auth_mode: "api_key", generation: 2, status: "active" },
  { id: "c2", provider_type: "parallel", owner_scope: "system", label: "Shared Parallel", auth_mode: "oauth", generation: 1, status: "active" },
]
const PROJECTS = [projectFixture(), projectFixture({ id: PROJECT_BETA_ID, name: "Beta", slug: "beta" })]

function installSystemStub(grants: unknown[] = []) {
  return installWorkspaceStub(
    (req) => {
      if (req.method === "GET" && req.url === "/api/v1/system/credentials") return ok(ROWS)
      if (req.method === "POST" && req.url === "/api/v1/system/credentials") {
        const body = req.body as { label: string; provider_type: string; auth_mode: string }
        return ok({ id: "c3", provider_type: body.provider_type, owner_scope: "system", label: body.label, auth_mode: body.auth_mode, generation: 1, status: "active" }, 201)
      }
      if (req.method === "GET" && req.url === "/api/v1/system/credentials/c1/grants") return ok(grants)
      if (req.method === "PUT" && req.url.startsWith("/api/v1/system/credentials/c1/grants/")) {
        const projectId = req.url.split("/").pop() ?? ""
        return ok({ credential_id: "c1", project_id: projectId, permitted_operations: (req.body as { permitted_operations: string[] }).permitted_operations, version: 1 })
      }
      if (req.method === "POST" && req.url.endsWith("/rotate")) return ok({ ...ROWS[0], generation: 3 })
      if (req.method === "DELETE") return new Response(null, { status: 204 })
      return err(404, null)
    },
    { projects: PROJECTS }
  )
}

beforeEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
})
afterEach(() => vi.unstubAllGlobals())

describe("SystemCredentialsPage", () => {
  it("lists system credential metadata", async () => {
    installSystemStub()
    renderInWorkspace(<SystemCredentialsPage />)
    expect(await screen.findByRole("heading", { level: 1, name: "System credentials" })).toBeInTheDocument()
    const table = await screen.findByRole("table", { name: "System credentials" })
    expect(within(table).getByText("Brave Search")).toBeInTheDocument()
    expect(within(table).getByText("Shared Brave")).toBeInTheDocument()
    expect(within(table).getByRole("button", { name: "Rotate key Shared Brave" })).toBeInTheDocument()
    expect(within(table).getByRole("button", { name: "Connect Shared Parallel" })).toBeInTheDocument()
    expect(within(table).getByRole("button", { name: "Disconnect Shared Parallel" })).toBeInTheDocument()
  })

  it("creates a credential and keeps the key out of DOM, storage and URL", async () => {
    const stub = installSystemStub()
    const user = userEvent.setup()
    renderInWorkspace(<SystemCredentialsPage />)
    await user.click(await screen.findByRole("button", { name: "Add system credential" }))
    const dialog = await screen.findByRole("dialog", { name: "Add system credential" })
    await user.selectOptions(within(dialog).getByLabelText("Provider"), "brave")
    await user.type(within(dialog).getByLabelText("Label"), "Brave prod")
    await user.type(within(dialog).getByLabelText("API key", SECRET), FAKE_PROVIDER_KEY)
    await user.click(within(dialog).getByRole("button", { name: "Save key" }))
    expect(await screen.findByText("Key saved for Brave prod.")).toBeInTheDocument()
    expect(stub.requests.find((req) => req.method === "POST")?.body).toEqual({ provider_type: "brave", label: "Brave prod", auth_mode: "api_key", secret: FAKE_PROVIDER_KEY })
    expect(leakedAnywhere(FAKE_PROVIDER_KEY)).toEqual([])
  })

  it("rotates with the row generation", async () => {
    const stub = installSystemStub()
    const user = userEvent.setup()
    renderInWorkspace(<SystemCredentialsPage />)
    await user.click(await screen.findByRole("button", { name: "Rotate key Shared Brave" }))
    const dialog = await screen.findByRole("dialog", { name: "Rotate Shared Brave" })
    await user.type(within(dialog).getByLabelText("New API key"), FAKE_PROVIDER_KEY)
    await user.click(within(dialog).getByRole("button", { name: "Rotate key" }))
    await screen.findByText("Key saved for Shared Brave.")
    expect(stub.requests.find((req) => req.url.endsWith("/rotate"))?.body).toEqual({ expected_generation: 2, secret: FAKE_PROVIDER_KEY })
    expect(leakedAnywhere(FAKE_PROVIDER_KEY)).toEqual([])
  })

  it("lists grants by project name, offers only supported operations, and saves and removes", async () => {
    const stub = installSystemStub([{ credential_id: "c1", project_id: PROJECT_ALPHA_ID, permitted_operations: ["search"], version: 1 }])
    const user = userEvent.setup()
    renderInWorkspace(<SystemCredentialsPage />)
    await user.click(await screen.findByRole("button", { name: "Grants Shared Brave" }))
    const dialog = await screen.findByRole("dialog", { name: "Project grants" })
    const table = await within(dialog).findByRole("table", { name: "Project grants" })
    expect(within(table).getByText("Alpha")).toBeInTheDocument()
    expect(within(dialog).getByRole("checkbox", { name: "Search" })).toBeInTheDocument()
    expect(within(dialog).queryByRole("checkbox", { name: "Fetch" })).toBeNull()

    await user.selectOptions(within(dialog).getByLabelText("Project"), PROJECT_BETA_ID)
    await user.click(within(dialog).getByRole("button", { name: "Save grant" }))
    await waitFor(() => expect(stub.requests.find((req) => req.method === "PUT")?.url).toBe(`/api/v1/system/credentials/c1/grants/${PROJECT_BETA_ID}`))
    expect(stub.requests.find((req) => req.method === "PUT")?.body).toEqual({ permitted_operations: ["search"] })

    await user.click(within(dialog).getByRole("button", { name: "Remove grant Alpha" }))
    await waitFor(() => expect(stub.requests.find((req) => req.method === "DELETE")?.url).toBe(`/api/v1/system/credentials/c1/grants/${PROJECT_ALPHA_ID}`))
  })
})
