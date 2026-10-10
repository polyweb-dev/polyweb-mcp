import { describe, expect, it } from "vitest"
import {
  TAB_PATHS,
  canAccessRoute,
  isInternalPath,
  loginPathFor,
  returnDestination,
} from "@/app/routes"
import type { TabId } from "@/app/routes"
import type { UserRole } from "@/domains/auth/model/types"

const ALL_TABS: TabId[] = [
  "playground",
  "routing",
  "quotas",
  "activity",
  "settings",
  "account",
  "adminUsers",
]

const DEVELOPER_TABS: TabId[] = [
  "playground",
  "routing",
  "quotas",
  "activity",
  "settings",
  "account",
]

const AGENT_TABS: TabId[] = ["playground", "activity", "account"]
const AGENT_DENIED_TABS: TabId[] = ["routing", "quotas", "settings", "adminUsers"]

describe("TAB_PATHS", () => {
  it("maps every tab id to its exact path", () => {
    expect(TAB_PATHS).toEqual({
      playground: "/playground",
      routing: "/routing",
      quotas: "/usage",
      activity: "/activity",
      settings: "/settings",
      account: "/account",
      adminUsers: "/admin/users",
    })
  })
})

describe("canAccessRoute", () => {
  it.each(ALL_TABS)("grants admin access to %s", (id) => {
    expect(canAccessRoute(id, "admin" satisfies UserRole)).toBe(true)
  })

  it.each(DEVELOPER_TABS)("grants developer access to %s", (id) => {
    expect(canAccessRoute(id, "developer" satisfies UserRole)).toBe(true)
  })

  it("denies developer access to adminUsers", () => {
    expect(canAccessRoute("adminUsers", "developer")).toBe(false)
  })

  it.each(AGENT_TABS)("grants agent access to %s", (id) => {
    expect(canAccessRoute(id, "agent" satisfies UserRole)).toBe(true)
  })

  it.each(AGENT_DENIED_TABS)("denies agent access to %s", (id) => {
    expect(canAccessRoute(id, "agent" satisfies UserRole)).toBe(false)
  })
})

describe("isInternalPath", () => {
  it.each([
    "/playground",
    "/routing",
    "/usage",
    "/activity",
    "/settings",
    "/account",
    "/admin/users",
  ])("accepts the internal path %s", (path) => {
    expect(isInternalPath(path)).toBe(true)
  })

  it.each(["", "playground", "//evil", "https://evil", "/unknown"])(
    "rejects the foreign value %s",
    (path) => {
      expect(isInternalPath(path)).toBe(false)
    }
  )

  it("rejects null and undefined", () => {
    expect(isInternalPath(null)).toBe(false)
    expect(isInternalPath(undefined)).toBe(false)
  })
})

describe("loginPathFor", () => {
  it("keeps an internal destination in the returnTo query", () => {
    expect(loginPathFor("/playground")).toBe("/login?returnTo=%2Fplayground")
    expect(loginPathFor("/admin/users")).toBe("/login?returnTo=%2Fadmin%2Fusers")
  })

  it.each(["https://evil", "//evil", "/unknown", ""])(
    "drops the foreign destination %s",
    (path) => {
      expect(loginPathFor(path)).toBe("/login")
    }
  )
})

describe("returnDestination", () => {
  it("keeps a validated internal destination", () => {
    expect(returnDestination("/routing")).toBe("/routing")
    expect(returnDestination("/admin/users")).toBe("/admin/users")
  })

  it.each(["https://evil", "//evil", "/unknown", ""])(
    "falls back to the playground for %s",
    (path) => {
      expect(returnDestination(path)).toBe("/playground")
    }
  )

  it("falls back to the playground for null and undefined", () => {
    expect(returnDestination(null)).toBe("/playground")
    expect(returnDestination(undefined)).toBe("/playground")
  })
})
