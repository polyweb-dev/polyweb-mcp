import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import { ProjectsProvider } from "./ProjectsProvider"
import { ProjectScopeProvider } from "./ProjectScopeProvider"
import { useProjectScope } from "./useProjectScope"

const ACCESS_A = { project_id: "p-a", permissions: ["project.read"], roles: ["project_member"], policy_revision: 1 }
const ACCESS_B = { project_id: "p-b", permissions: ["members.manage"], roles: ["project_admin"], policy_revision: 3 }

function Probe() {
  const { accessState } = useProjectScope()
  return (
    <span data-testid="access">
      {accessState.status === "ready" ? accessState.data.roles.join(",") : accessState.status}
    </span>
  )
}

function stubAll() {
  return installFetchStub((req) => {
    if (req.url === "/api/v1/system/access") return ok({ rollout_state: "preview", permissions: [] })
    if (req.url === "/api/v1/projects?include_archived=true") return ok([])
    if (req.url === "/api/v1/projects/p-a/access") return ok(ACCESS_A)
    if (req.url === "/api/v1/projects/p-b/access") return ok(ACCESS_B)
    return err(404, null)
  })
}

describe("ProjectScopeProvider", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("loads the access of the scoped project", async () => {
    stubAll()
    render(
      <ProjectsProvider accountId="acc">
        <ProjectScopeProvider accountId="acc" projectId="p-a">
          <Probe />
        </ProjectScopeProvider>
      </ProjectsProvider>
    )
    await waitFor(() =>
      expect(screen.getByTestId("access").textContent).toBe("project_member")
    )
  })

  it("resets to the new scope when the key remounts", async () => {
    stubAll()
    const rendered = render(
      <ProjectsProvider accountId="acc">
        <ProjectScopeProvider key="acc:p-a" accountId="acc" projectId="p-a">
          <Probe />
        </ProjectScopeProvider>
      </ProjectsProvider>
    )
    await waitFor(() =>
      expect(screen.getByTestId("access").textContent).toBe("project_member")
    )
    rendered.rerender(
      <ProjectsProvider accountId="acc">
        <ProjectScopeProvider key="acc:p-b" accountId="acc" projectId="p-b">
          <Probe />
        </ProjectScopeProvider>
      </ProjectsProvider>
    )
    await waitFor(() =>
      expect(screen.getByTestId("access").textContent).toBe("project_admin")
    )
  })
})
