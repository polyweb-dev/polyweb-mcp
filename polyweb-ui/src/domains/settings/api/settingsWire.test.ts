import { describe, expect, it } from "vitest"
import { decodeCopyPlan, decodeProjectSettings, decodeSettingsValue } from "./settingsWire"

function fieldWire(overrides: Record<string, unknown> = {}) {
  return {
    field_name: "trace.retention_days",
    section: "trace",
    effective_value: 30,
    provenance: "system_default",
    is_null: false,
    system_default: 30,
    project_override: null,
    source_scope: "system",
    override_allowed: true,
    system_safety_limit: 90,
    constraint_applied: false,
    ...overrides,
  }
}

describe("decodeSettingsValue", () => {
  it("keeps JSON scalars and string lists only", () => {
    expect(decodeSettingsValue("x")).toBe("x")
    expect(decodeSettingsValue(0)).toBe(0)
    expect(decodeSettingsValue(false)).toBe(false)
    expect(decodeSettingsValue(["a", "b"])).toEqual(["a", "b"])
    expect(decodeSettingsValue({ nested: 1 })).toBeNull()
    expect(decodeSettingsValue([1])).toBeNull()
    expect(decodeSettingsValue(Number.NaN)).toBeNull()
  })
})

describe("decodeProjectSettings", () => {
  it("decodes fields with provenance, default and limit, and drops system-only ones", () => {
    const settings = decodeProjectSettings({
      namespace: "settings",
      fields: {
        "trace.retention_days": fieldWire({ project_override: 120, effective_value: 90, provenance: "system_constrained", constraint_applied: true }),
        "system.max_trace_retention_days": fieldWire({ section: "safety_limits", override_allowed: false }),
        "bad.field": { provenance: "nope" },
      },
      effective_settings: {},
      provenance_by_field: {},
      system_revision: 3,
      project_revision: 7,
    })
    expect(settings.systemRevision).toBe(3)
    expect(settings.projectRevision).toBe(7)
    expect(settings.fields).toEqual([
      {
        id: "trace.retention_days",
        section: "trace",
        attribute: "retention_days",
        effectiveValue: 90,
        provenance: "system_constrained",
        systemDefault: 30,
        projectOverride: 120,
        overrideAllowed: true,
        systemLimit: 90,
        constraintApplied: true,
      },
    ])
  })

  it("treats a missing project revision as zero and rejects a missing system revision", () => {
    expect(decodeProjectSettings({ fields: {}, system_revision: 0, project_revision: null }).projectRevision).toBe(0)
    expect(() => decodeProjectSettings({ fields: {} })).toThrow()
  })
})

describe("decodeCopyPlan", () => {
  it("decodes revisions, fields, rejections and bindings", () => {
    const plan = decodeCopyPlan({
      source_project_id: "src",
      target_project_id: "tgt",
      mode: "overrides_only",
      source_revision: 2,
      target_revision: 5,
      system_revision: 1,
      overrides: {},
      effective_snapshot: {},
      fields: [{ field_id: "routing.max_attempts", section: "routing", attribute: "max_attempts", provenance: "project_override", value: 4, changed: true }],
      rejected: [{ field_id: "binding:b2", reason: "credential not granted" }],
      bindings: [{ binding_id: "b1", credential_id: "c1", route_label: "primary", version: 3, selected: false, eligible: true, rejection: null }],
      target: {},
    })
    expect(plan).toMatchObject({ sourceRevision: 2, targetRevision: 5, systemRevision: 1, mode: "overrides_only" })
    expect(plan.fields[0]).toMatchObject({ fieldId: "routing.max_attempts", value: 4, changed: true })
    expect(plan.rejected).toEqual([{ fieldId: "binding:b2", reason: "credential not granted" }])
    expect(plan.bindings[0]).toMatchObject({ bindingId: "b1", version: 3, eligible: true })
  })

  it("rejects a plan without revisions", () => {
    expect(() => decodeCopyPlan({ mode: "overrides_only" })).toThrow()
  })
})
