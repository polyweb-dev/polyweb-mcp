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
import { projectConflictCode } from "./projectsApi"

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
    expect(LAST_PROJECT_ADMIN_MESSAGE).toBe(
      "A project must keep at least one active administrator. Make another active member a project admin first."
    )
  })

  it("reads the conflict code of a 409 body only", () => {
    const conflict = new ApiError(409, "", { detail: { code: "PROJECT_ARCHIVED", message: "x" } })
    expect(projectConflictCode(conflict)).toBe("PROJECT_ARCHIVED")
    expect(projectMutationMessage(conflict, "x")).toBe("An archived project cannot change its members.")
    expect(projectConflictCode(new ApiError(400, "", { detail: { code: "X" } }))).toBeNull()
    expect(projectConflictCode(new ApiError(409, "", { detail: "plain" }))).toBeNull()
    expect(projectConflictCode(new ApiError(409, "", null))).toBeNull()
    expect(projectConflictCode(new Error("x"))).toBeNull()
  })

  it("maps a 400 to the unknown-email copy only on an email lookup", async () => {
    installFetchStub(() => err(400, null))
    const bad = await addProjectMember("p1", { email: "x@y.io", initial_role: "project_member" }).catch(
      (e: unknown) => e
    )
    expect(projectMutationMessage(bad, "x", { emailLookup: true })).toBe(UNKNOWN_ACCOUNT_EMAIL_MESSAGE)
    expect(projectMutationMessage(bad, "The change could not be saved.")).toBe(
      "The change could not be saved."
    )
    expect(projectMutationMessage(bad, "fallback", { emailLookup: false })).toBe("fallback")
  })

  it("shows the server detail of a 400 with a body outside an email lookup", () => {
    const withDetail = new ApiError(400, "slug already in use", { detail: "slug already in use" })
    expect(projectMutationMessage(withDetail, "fallback")).toBe("slug already in use")
  })

  it("falls back for a bare failure and maps 403 to the permission copy", () => {
    expect(projectMutationMessage(new ApiError(500, "Unknown API error", undefined), "fallback")).toBe("fallback")
    expect(projectMutationMessage(new Error("boom"), "fallback")).toBe("fallback")
    const denied = new ApiError(403, "", null)
    expect(projectMutationMessage(denied, "x")).toBe(PERMISSION_LOST_MESSAGE)
    expect(projectMutationMessage(denied, "x", { emailLookup: true })).toBe(PERMISSION_LOST_MESSAGE)
    expect(isProjectUnavailableError(new ApiError(404, "", null))).toBe(true)
    expect(isProjectUnavailableError(new ApiError(403, "", null))).toBe(false)
  })
})
