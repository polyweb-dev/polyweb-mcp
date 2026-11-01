import { describe, expect, it } from "vitest"
import {
  LEGACY_SECTION_PATHS,
  PROJECT_SECTIONS,
  TAB_PATHS,
  canAccessProjectSection,
  canAccessRoute,
  isGatedRoute,
  isInternalPath,
  loginPathFor,
  parseProjectPath,
  projectIdFromPath,
  projectPath,
  returnDestination,
} from "@/app/routes"
import type { TabId } from "@/app/routes"
import {
  PROJECT_ADMIN_PERMISSIONS,
  PROJECT_MEMBER_PERMISSIONS,
  SETTINGS_READER_PERMISSIONS,
  SYSTEM_ADMIN_PERMISSIONS,
  projectAccessFixture,
  systemAccessFixture,
} from "@/test/accessFixtures"

const ALL_TABS: TabId[] = [
  "routing",
  "quotas",
  "settings",
  "projects",
  "account",
  "adminUsers",
]

const SETTINGS_READER_TABS: TabId[] = [
  "routing",
  "quotas",
  "settings",
  "projects",
  "account",
]

const OPEN_TABS: TabId[] = ["projects", "account"]
const SETTINGS_TABS: TabId[] = ["routing", "quotas", "settings"]

const PROJECT_ID = "11111111-1111-4111-8111-111111111111"

describe("TAB_PATHS", () => {
  it("maps every tab id to its exact path", () => {
    expect(TAB_PATHS).toEqual({
      routing: "/routing",
      quotas: "/usage",
      settings: "/settings",
      projects: "/projects",
      account: "/account",
      adminUsers: "/admin/users",
    })
  })
})

describe("canAccessRoute", () => {
  it.each(ALL_TABS)("grants the system administrator access to %s", (id) => {
    expect(canAccessRoute(id, systemAccessFixture(SYSTEM_ADMIN_PERMISSIONS))).toBe(true)
  })

  it.each(SETTINGS_READER_TABS)("grants system.settings.read access to %s", (id) => {
    expect(canAccessRoute(id, systemAccessFixture(SETTINGS_READER_PERMISSIONS))).toBe(true)
  })

  it("denies adminUsers without system.settings.write", () => {
    expect(canAccessRoute("adminUsers", systemAccessFixture(SETTINGS_READER_PERMISSIONS))).toBe(false)
  })

  it("grants adminUsers with system.settings.write alone", () => {
    expect(canAccessRoute("adminUsers", systemAccessFixture(["system.settings.write"]))).toBe(true)
  })

  it.each(OPEN_TABS)("grants access to %s without any system permission", (id) => {
    expect(canAccessRoute(id, systemAccessFixture([]))).toBe(true)
    expect(canAccessRoute(id, null)).toBe(true)
  })

  it.each([...SETTINGS_TABS, "adminUsers" as const])(
    "denies %s without any system permission or before access loads",
    (id) => {
      expect(canAccessRoute(id, systemAccessFixture([]))).toBe(false)
      expect(canAccessRoute(id, null)).toBe(false)
    }
  )

  it("ignores project permissions that share a suffix with a system permission", () => {
    expect(canAccessRoute("settings", systemAccessFixture(["settings.read"]))).toBe(false)
  })
})

describe("isGatedRoute", () => {
  it("marks exactly the settings and admin routes as gated", () => {
    expect(ALL_TABS.filter(isGatedRoute)).toEqual(["routing", "quotas", "settings", "adminUsers"])
  })
})

describe("project section registry", () => {
  it("lists the project sections in sidebar order with their any-of permissions", () => {
    expect(PROJECT_SECTIONS.map(({ id, segment, label, permissions }) => ({ id, segment, label, permissions }))).toEqual([
      { id: "overview", segment: "", label: "Overview", permissions: ["project.read"] },
      {
        id: "playground",
        segment: "playground",
        label: "Playground",
        permissions: ["search.execute", "fetch.execute"],
      },
      { id: "activity", segment: "activity", label: "Activity", permissions: ["traces.read"] },
      { id: "usage", segment: "usage", label: "Usage", permissions: ["usage.read"] },
      { id: "members", segment: "members", label: "Members", permissions: ["members.read"] },
      { id: "apiKeys", segment: "api-keys", label: "API keys", permissions: ["tokens.manage"] },
    ])
  })

  it("maps the former global paths to their project sections", () => {
    expect(LEGACY_SECTION_PATHS).toEqual({ "/playground": "playground", "/activity": "activity" })
  })

  it("builds the path of every registered section", () => {
    expect(projectPath(PROJECT_ID)).toBe(`/p/${PROJECT_ID}`)
    expect(projectPath(PROJECT_ID, "overview")).toBe(`/p/${PROJECT_ID}`)
    expect(projectPath(PROJECT_ID, "playground")).toBe(`/p/${PROJECT_ID}/playground`)
    expect(projectPath(PROJECT_ID, "activity")).toBe(`/p/${PROJECT_ID}/activity`)
    expect(projectPath(PROJECT_ID, "usage")).toBe(`/p/${PROJECT_ID}/usage`)
    expect(projectPath(PROJECT_ID, "members")).toBe(`/p/${PROJECT_ID}/members`)
    expect(projectPath(PROJECT_ID, "apiKeys")).toBe(`/p/${PROJECT_ID}/api-keys`)
  })

  it("parses a registered section and rejects an unknown one", () => {
    expect(parseProjectPath(`/p/${PROJECT_ID}`)).toEqual({ projectId: PROJECT_ID, section: "overview" })
    expect(parseProjectPath(`/p/${PROJECT_ID}/api-keys`)).toEqual({ projectId: PROJECT_ID, section: "apiKeys" })
    expect(parseProjectPath(`/p/${PROJECT_ID}/usage`)).toEqual({ projectId: PROJECT_ID, section: "usage" })
    expect(parseProjectPath(`/p/${PROJECT_ID}/settings`)).toBeNull()
    expect(parseProjectPath("/playground")).toBeNull()
  })

  it("reads the project id of any project URL", () => {
    expect(projectIdFromPath(`/p/${PROJECT_ID}/usage`)).toBe(PROJECT_ID)
    expect(projectIdFromPath(`/p/${PROJECT_ID}`)).toBe(PROJECT_ID)
    expect(projectIdFromPath("/projects")).toBeNull()
    expect(projectIdFromPath("/p/")).toBeNull()
  })

  it("opens a section only with its project permission", () => {
    const admin = projectAccessFixture(PROJECT_ID, PROJECT_ADMIN_PERMISSIONS)
    const member = projectAccessFixture(PROJECT_ID, PROJECT_MEMBER_PERMISSIONS)
    expect(canAccessProjectSection("apiKeys", admin)).toBe(true)
    expect(canAccessProjectSection("apiKeys", member)).toBe(false)
    expect(canAccessProjectSection("members", member)).toBe(true)
    expect(canAccessProjectSection("overview", projectAccessFixture(PROJECT_ID, ["tokens.manage"]))).toBe(false)
    expect(canAccessProjectSection("overview", null)).toBe(false)
  })

  it("opens the playground with either execution permission (any-of)", () => {
    const search = projectAccessFixture(PROJECT_ID, ["project.read", "search.execute"])
    const fetch = projectAccessFixture(PROJECT_ID, ["project.read", "fetch.execute"])
    const neither = projectAccessFixture(PROJECT_ID, ["project.read", "traces.read"])
    expect(canAccessProjectSection("playground", search)).toBe(true)
    expect(canAccessProjectSection("playground", fetch)).toBe(true)
    expect(canAccessProjectSection("playground", neither)).toBe(false)
    expect(canAccessProjectSection("activity", neither)).toBe(true)
    expect(canAccessProjectSection("usage", neither)).toBe(false)
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

  it.each([
    "/projects",
    "/p/11111111-1111-4111-8111-111111111111",
    "/p/11111111-1111-4111-8111-111111111111/members",
    "/p/11111111-1111-4111-8111-111111111111/api-keys",
    "/p/11111111-1111-4111-8111-111111111111/playground",
    "/p/11111111-1111-4111-8111-111111111111/activity",
    "/p/11111111-1111-4111-8111-111111111111/usage",
  ])("accepts the project path %s", (path) => {
    expect(isInternalPath(path)).toBe(true)
  })

  it.each([
    "/p/not-a-uuid",
    "/p/not-a-uuid/api-keys",
    "/p/11111111-1111-4111-8111-111111111111/settings",
    "/p/11111111-1111-4111-8111-111111111111/members/extra",
    "/projects/create",
  ])("rejects the non-project path %s", (path) => {
    expect(isInternalPath(path)).toBe(false)
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
    "falls back to the workspace entry for %s",
    (path) => {
      expect(returnDestination(path)).toBe("/")
    }
  )

  it("falls back to the workspace entry for null and undefined", () => {
    expect(returnDestination(null)).toBe("/")
    expect(returnDestination(undefined)).toBe("/")
  })
})
