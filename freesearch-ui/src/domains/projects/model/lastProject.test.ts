import { afterEach, describe, expect, it } from "vitest"
import {
  lastProjectKey,
  readLastProject,
  resolveLastProject,
  writeLastProject,
} from "@/domains/projects"

describe("lastProject", () => {
  afterEach(() => window.localStorage.clear())

  it("keys the preference per account", () => {
    expect(lastProjectKey("acc")).toBe("freesearch:last-project:v1:acc")
  })

  it("remembers a project per account without leaking across accounts", () => {
    writeLastProject("a", "p1")
    expect(readLastProject("a")).toBe("p1")
    expect(readLastProject("b")).toBeNull()
  })

  it("resolves only ids that are still in the project list", () => {
    writeLastProject("a", "p1")
    expect(resolveLastProject("a", [{ id: "p1" }, { id: "p2" }])).toBe("p1")
    expect(resolveLastProject("a", [{ id: "p2" }])).toBeNull()
    expect(resolveLastProject("a", [])).toBeNull()
  })
})
