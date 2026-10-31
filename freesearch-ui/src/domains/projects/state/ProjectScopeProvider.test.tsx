import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import { ProjectsProvider } from "./ProjectsProvider"
import { ProjectScopeProvider } from "./ProjectScopeProvider"
import { useProjectScope, useProjectScopeOptional } from "./useProjectScope"

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

function OptionalProbe() {
  const scope = useProjectScopeOptional()
  return <span data-testid="scope">{scope === null ? "none" : scope.projectId}</span>
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

  it("switches scope in place: the old access never shows under the new project", async () => {
    stubAll()
    const rendered = render(
      <ProjectsProvider accountId="acc">
        <ProjectScopeProvider accountId="acc" projectId="p-a">
          <Probe />
        </ProjectScopeProvider>
      </ProjectsProvider>
    )
    await waitFor(() => expect(screen.getByTestId("access").textContent).toBe("project_member"))
    rendered.rerender(
      <ProjectsProvider accountId="acc">
        <ProjectScopeProvider accountId="acc" projectId="p-b">
          <Probe />
        </ProjectScopeProvider>
      </ProjectsProvider>
    )
    expect(screen.getByTestId("access").textContent).toBe("loading")
    await waitFor(() => expect(screen.getByTestId("access").textContent).toBe("project_admin"))
  })

  it("provides no scope and sends no access read for a global route", async () => {
    const stub = stubAll()
    render(
      <ProjectsProvider accountId="acc">
        <ProjectScopeProvider accountId="acc" projectId={null}>
          <OptionalProbe />
        </ProjectScopeProvider>
      </ProjectsProvider>
    )
    expect(screen.getByTestId("scope").textContent).toBe("none")
    await waitFor(() => expect(stub.requestsTo("/api/v1/system/access")).toHaveLength(1))
    expect(stub.requestsTo(/\/access$/).filter((req) => req.url.includes("/projects/"))).toHaveLength(0)
  })

  it("rejects useProjectScope outside a project", () => {
    stubAll()
    const silence = vi.spyOn(console, "error").mockImplementation(() => {})
    expect(() =>
      render(
        <ProjectsProvider accountId="acc">
          <ProjectScopeProvider accountId="acc" projectId={null}>
            <Probe />
          </ProjectScopeProvider>
        </ProjectsProvider>
      )
    ).toThrow("useProjectScope must be used inside ProjectScopeProvider")
    silence.mockRestore()
  })
})
