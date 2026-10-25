import { afterEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/shared/api/http"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import {
  LAST_PROJECT_ADMIN_MESSAGE,
  PERMISSION_LOST_MESSAGE,
  UNKNOWN_ACCOUNT_EMAIL_MESSAGE,
  addProjectMember,
  createProject,
  getProjectAccess,
  getSystemAccess,
  isLastProjectAdminError,
  isProjectUnavailableError,
  listProjectMembers,
  listProjects,
  projectMutationMessage,
  removeProjectMember,
  removeProjectRole,
  assignProjectRole,
  setProjectMemberStatus,
} from "@/domains/projects"

const ACCESS_BODY = { rollout_state: "preview", permissions: ["project.create"] }
const PROJECT_ACCESS_BODY = {
  project_id: "p",
  permissions: ["members.read"],
  roles: ["project_member"],
  policy_revision: 1,
}
const MEMBER_BODY = {
  project_id: "p",
  user_id: "u",
  email: "m@example.com",
  status: "active",
  roles: ["project_member"],
  version: 1,
}

describe("projectsApi", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("sends GET /api/v1/system/access with the caller signal", async () => {
    const stub = installFetchStub(() => ok(ACCESS_BODY))
    const controller = new AbortController()
    const access = await getSystemAccess(controller.signal)
    expect(access).toEqual(ACCESS_BODY)
    expect(stub.requests[0]?.url).toBe("/api/v1/system/access")
    expect(stub.requests[0]?.signal).toBe(controller.signal)
  })

  it("requests the project list with archived included", async () => {
    const stub = installFetchStub(() => ok([]))
    expect(await listProjects(new AbortController().signal)).toEqual([])
    expect(stub.requests[0]?.url).toBe("/api/v1/projects?include_archived=true")
  })

  it("creates a project by first-admin email", async () => {
    const stub = installFetchStub(() =>
      ok({ id: "p1", account_id: "a", name: "N", slug: "n", status: "active", created_by: "u", created_at: "t", version: 1 }, 201)
    )
    const created = await createProject({ name: "N", initial_admin_email: " a@x.io " })
    expect(created.id).toBe("p1")
    expect(stub.requests[0]?.body).toEqual({ name: "N", initial_admin_email: " a@x.io " })
  })

  it("maps project endpoints for access, members, and mutations", async () => {
    const stub = installFetchStub((req) => {
      if (req.url.endsWith("/access")) return ok(PROJECT_ACCESS_BODY)
      if (req.url.endsWith("/members") && req.method === "GET") return ok([MEMBER_BODY])
      return ok(MEMBER_BODY)
    })
    const signal = new AbortController().signal
    await getProjectAccess("p1", signal)
    await listProjectMembers("p1", signal)
    await addProjectMember("p1", { email: "m@example.com", initial_role: "project_member" })
    await setProjectMemberStatus("p1", "u1", "suspended")
    await removeProjectMember("p1", "u1")
    await assignProjectRole("p1", "u1", "routing_editor")
    await removeProjectRole("p1", "u1", "routing_editor")
    const urls = stub.requests.map((r) => `${r.method} ${r.url}`)
    expect(urls).toEqual([
      "GET /api/v1/projects/p1/access",
      "GET /api/v1/projects/p1/members",
      "POST /api/v1/projects/p1/members",
      "PATCH /api/v1/projects/p1/members/u1",
      "DELETE /api/v1/projects/p1/members/u1",
      "PUT /api/v1/projects/p1/members/u1/roles/routing_editor",
      "DELETE /api/v1/projects/p1/members/u1/roles/routing_editor",
    ])
  })

  it("detects the LAST_PROJECT_ADMIN conflict from the 409 body", async () => {
    installFetchStub(() =>
      err(409, { detail: { code: "LAST_PROJECT_ADMIN", message: "last" } })
    )
    const failure = await removeProjectMember("p1", "u1").catch((e: unknown) => e)
    expect(isLastProjectAdminError(failure)).toBe(true)
    expect(projectMutationMessage(failure, "x")).toBe(LAST_PROJECT_ADMIN_MESSAGE)
  })

  it("maps 400 to the unknown-email copy and 403 to the permission copy", async () => {
    installFetchStub(() => err(400, null))
    const bad = await addProjectMember("p1", { email: "x@y.io", initial_role: "project_member" }).catch(
      (e: unknown) => e
    )
    expect(projectMutationMessage(bad, "x")).toBe(UNKNOWN_ACCOUNT_EMAIL_MESSAGE)
    const denied = new ApiError(403, "", null)
    expect(projectMutationMessage(denied, "x")).toBe(PERMISSION_LOST_MESSAGE)
    expect(isProjectUnavailableError(new ApiError(404, "", null))).toBe(true)
    expect(isProjectUnavailableError(new ApiError(403, "", null))).toBe(false)
  })
})
