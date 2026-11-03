import { describe, expect, it } from "vitest"
import type { SettingsField } from "@/domains/settings"
import { controlValue, isInheritPending, parseList, sectionChanges, withoutSection } from "./settingsDraft"

function field(id: string, overrides: Partial<SettingsField> = {}): SettingsField {
  return {
    id,
    section: id.split(".")[0] ?? "",
    attribute: id.split(".")[1] ?? "",
    effectiveValue: 3,
    provenance: "system_default",
    systemDefault: 3,
    projectOverride: null,
    overrideAllowed: true,
    systemLimit: null,
    constraintApplied: false,
    ...overrides,
  }
}

const ATTEMPTS = field("routing.max_attempts", { projectOverride: 5, effectiveValue: 5, provenance: "project_override" })
const PREFERRED = field("routing.preferred_providers", { effectiveValue: [], systemDefault: [] })
const RETENTION = field("trace.retention_days", { effectiveValue: 30, systemDefault: 30 })
const FIELDS = [ATTEMPTS, PREFERRED, RETENTION]

describe("sectionChanges", () => {
  it("sends only changed fields of one section", () => {
    const draft = { "routing.max_attempts": 5, "routing.preferred_providers": ["tavily"], "trace.retention_days": 10 }
    expect(sectionChanges(draft, FIELDS, "routing")).toEqual({ "routing.preferred_providers": ["tavily"] })
    expect(sectionChanges(draft, FIELDS, "trace")).toEqual({ "trace.retention_days": 10 })
  })

  it("sends null for an inherited override and nothing for inheriting an inherited field", () => {
    expect(sectionChanges({ "routing.max_attempts": null }, FIELDS, "routing")).toEqual({ "routing.max_attempts": null })
    expect(sectionChanges({ "trace.retention_days": null }, FIELDS, "trace")).toEqual({})
  })
})

describe("draft display helpers", () => {
  it("shows the draft, the system default on inherit, else the effective value", () => {
    expect(controlValue({}, ATTEMPTS)).toBe(5)
    expect(controlValue({ "routing.max_attempts": 7 }, ATTEMPTS)).toBe(7)
    expect(controlValue({ "routing.max_attempts": null }, ATTEMPTS)).toBe(3)
    expect(isInheritPending({ "routing.max_attempts": null }, ATTEMPTS)).toBe(true)
    expect(isInheritPending({}, ATTEMPTS)).toBe(false)
  })

  it("drops one section's entries and parses lists", () => {
    expect(withoutSection({ "routing.max_attempts": 1, "trace.retention_days": 2 }, FIELDS, "routing")).toEqual({ "trace.retention_days": 2 })
    expect(parseList(" tavily, ,exa ")).toEqual(["tavily", "exa"])
  })
})
