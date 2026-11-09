import { describe, expect, it } from "vitest"
import type { SettingsField } from "./settings"
import {
  METADATA_ONLY_REASON,
  disabledOptionReason,
  numericMax,
} from "./tracePolicy"

function field(id: string, overrides: Partial<SettingsField> = {}): SettingsField {
  return {
    id,
    section: "trace",
    attribute: id.split(".")[1] ?? id,
    effectiveValue: null,
    provenance: "system_default",
    systemDefault: null,
    projectOverride: null,
    overrideAllowed: true,
    systemLimit: null,
    constraintApplied: false,
    ...overrides,
  }
}

describe("disabledOptionReason", () => {
  it("disables full payloads when the system allows metadata only", () => {
    const detail = field("trace.detail", { systemDefault: "metadata", systemLimit: "metadata" })
    expect(disabledOptionReason(detail, "full")).toBe(METADATA_ONLY_REASON)
    expect(disabledOptionReason(detail, "metadata")).toBeNull()
    expect(disabledOptionReason({ ...detail, systemLimit: "full", systemDefault: "full" }, "full")).toBeNull()
  })

  it("leaves unrelated settings unconstrained", () => {
    expect(disabledOptionReason(field("execution.cache_enabled"), "full")).toBeNull()
  })
})

describe("numericMax", () => {
  it("caps a numeric field at the system limit", () => {
    expect(numericMax(field("trace.retention_days", { systemLimit: 90 }), 365)).toBe(90)
    expect(numericMax(field("trace.retention_days"), 365)).toBe(365)
  })
})
