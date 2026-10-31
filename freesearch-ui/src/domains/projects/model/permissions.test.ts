import { describe, expect, it } from "vitest"
import { PROJECT_PERMISSIONS, SYSTEM_PERMISSIONS, canCreateProjects } from "./permissions"

describe("permission names", () => {
  it("mirror the backend action catalog", () => {
    expect(SYSTEM_PERMISSIONS).toEqual({
      settingsRead: "system.settings.read",
      settingsWrite: "system.settings.write",
      projectCreate: "project.create",
    })
    expect(PROJECT_PERMISSIONS).toEqual({
      read: "project.read",
      membersRead: "members.read",
      membersManage: "members.manage",
      rolesAssign: "roles.assign",
      tokensManage: "tokens.manage",
    })
  })
})

describe("canCreateProjects", () => {
  it("grants creation with project.create, the permission the backend enforces", () => {
    expect(canCreateProjects({ permissions: ["project.create"] })).toBe(true)
  })

  it("denies creation with system.projects.create alone, other permissions, or before access loads", () => {
    expect(canCreateProjects({ permissions: ["system.projects.create"] })).toBe(false)
    expect(canCreateProjects({ permissions: ["system.settings.write"] })).toBe(false)
    expect(canCreateProjects(null)).toBe(false)
    expect(canCreateProjects(undefined)).toBe(false)
  })
})
