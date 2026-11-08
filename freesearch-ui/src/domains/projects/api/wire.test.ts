import { describe, expect, it } from "vitest"
import { ApiError } from "@/shared/api/http"
import {
  decodeProjectAccess,
  decodeProjectList,
  decodeProjectMemberList,
  decodeSystemAccess,
} from "./wire"

const VALID_PROJECT = {
  id: "11111111-1111-4111-8111-111111111111",
  account_id: "00000000-0000-4000-8000-000000000001",
  name: "Alpha",
  slug: "alpha",
  status: "active",
  created_by: "22222222-2222-4222-8222-222222222222",
  created_at: "2026-01-01T00:00:00Z",
  version: 1,
}

const VALID_MEMBER = {
  project_id: VALID_PROJECT.id,
  user_id: "22222222-2222-4222-8222-222222222222",
  email: "member@example.com",
  status: "active",
  roles: ["project_admin"],
  version: 1,
  role: "admin",
  permissions: 33023,
  provider_owner: true,
}

describe("projects wire decoders", () => {
  it("decodes a system access payload", () => {
    expect(
      decodeSystemAccess({ rollout_state: "preview", permissions: ["project.create"] })
    ).toEqual({ rollout_state: "preview", permissions: ["project.create"] })
  })

  it("decodes a project list payload", () => {
    expect(decodeProjectList([VALID_PROJECT])).toEqual([VALID_PROJECT])
    expect(decodeProjectList([])).toEqual([])
  })

  it("decodes a project access payload", () => {
    const access = decodeProjectAccess({
      project_id: VALID_PROJECT.id,
      permissions: ["members.read"],
      roles: ["project_member"],
      policy_revision: 2,
    })
    expect(access.policy_revision).toBe(2)
    expect(access.roles).toEqual(["project_member"])
  })

  it("decodes a member list payload", () => {
    const developer = { ...VALID_MEMBER, role: "developer", roles: ["project_member"], permissions: 15, provider_owner: false }
    expect(decodeProjectMemberList([VALID_MEMBER, developer])).toEqual([VALID_MEMBER, developer])
  })

  it.each([
    ["system access with bad rollout", () => decodeSystemAccess({ rollout_state: "beta", permissions: [] })],
    ["system access with non-list permissions", () => decodeSystemAccess({ rollout_state: "preview", permissions: "x" })],
    ["project missing name", () => decodeProjectList([{ ...VALID_PROJECT, name: 7 }])],
    ["project non-list body", () => decodeProjectList({})],
    ["access missing revision", () => decodeProjectAccess({ project_id: "p", permissions: [], roles: [] })],
    ["member missing email", () => decodeProjectMemberList([{ ...VALID_MEMBER, email: 1 }])],
    ["member bad status", () => decodeProjectMemberList([{ ...VALID_MEMBER, status: "gone" }])],
    ["member role key instead of projection", () => decodeProjectMemberList([{ ...VALID_MEMBER, role: "project_admin" }])],
    ["member missing permissions", () => decodeProjectMemberList([{ ...VALID_MEMBER, permissions: undefined }])],
    ["member invalid owner flag", () => decodeProjectMemberList([{ ...VALID_MEMBER, provider_owner: "true" }])],
  ])("rejects %s", (_label, decode) => {
    expect(decode).toThrowError(ApiError)
    try {
      decode()
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      expect((error as ApiError).status).toBe(0)
      expect((error as ApiError).detail).toBe(
        "The server returned an unexpected project response."
      )
    }
  })
})
