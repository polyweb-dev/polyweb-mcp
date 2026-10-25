import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import { ProjectsProvider } from "./ProjectsProvider"
import { useProjects } from "./useProjects"

const SYSTEM_ACCESS = { rollout_state: "preview", permissions: [] }
const PROJECT = {
  id: "11111111-1111-4111-8111-111111111111",
  account_id: "a",
  name: "Alpha",
  slug: "alpha",
  status: "active",
  created_by: "u",
  created_at: "t",
  version: 1,
}

function Probe() {
  const { availability, rolloutState, projects } = useProjects()
  return (
    <div>
      <span data-testid="availability">{availability}</span>
      <span data-testid="rollout">{rolloutState ?? "none"}</span>
      <span data-testid="count">{projects.length}</span>
    </div>
  )
}

function stubProjects(systemStatus = 200) {
  return installFetchStub((req) => {
    if (req.url === "/api/v1/system/access") {
      return systemStatus === 200 ? ok(SYSTEM_ACCESS) : err(systemStatus, null)
    }
    if (req.url === "/api/v1/projects?include_archived=true") return ok([PROJECT])
    return err(404, { detail: "unhandled" })
  })
}

describe("ProjectsProvider", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("exposes available state with the loaded projects", async () => {
    stubProjects()
    render(
      <ProjectsProvider accountId="acc">
        <Probe />
      </ProjectsProvider>
    )
    await waitFor(() =>
      expect(screen.getByTestId("availability").textContent).toBe("available")
    )
    expect(screen.getByTestId("rollout").textContent).toBe("preview")
    expect(screen.getByTestId("count").textContent).toBe("1")
  })

  it("resolves unavailable when the system access read fails", async () => {
    stubProjects(404)
    render(
      <ProjectsProvider accountId="acc">
        <Probe />
      </ProjectsProvider>
    )
    await waitFor(() =>
      expect(screen.getByTestId("availability").textContent).toBe("unavailable")
    )
  })

  it("reloads on reloadProjects", async () => {
    const stub = stubProjects()
    render(
      <ProjectsProvider accountId="acc">
        <Probe />
      </ProjectsProvider>
    )
    await waitFor(() =>
      expect(screen.getByTestId("availability").textContent).toBe("available")
    )
    expect(stub.requestsTo("/api/v1/system/access").length).toBe(1)
  })
})
