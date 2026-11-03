import { describe, expect, it } from "vitest"
import type { SettingsField } from "./settings"
import {
  METADATA_ONLY_REASON,
  STRICT_REDACTION_REASON,
  disabledOptionReason,
  numericMax,
  tracePolicySummary,
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

const TRACE = [
  field("trace.sampling_rate", { effectiveValue: 0.25 }),
  field("trace.detail", { effectiveValue: "metadata" }),
  field("trace.payload_redaction", { effectiveValue: "strict" }),
  field("trace.retention_days", { effectiveValue: 30 }),
]

describe("tracePolicySummary", () => {
  it("summarizes the effective trace policy", () => {
    expect(tracePolicySummary(TRACE)).toBe(
      "New traces: 25% sampled, Metadata only, Strict redaction, kept 30 days."
    )
  })

  it("reads full payloads and standard redaction", () => {
    const fields = TRACE.map((entry) =>
      entry.id === "trace.detail"
        ? { ...entry, effectiveValue: "full" }
        : entry.id === "trace.payload_redaction"
          ? { ...entry, effectiveValue: "standard" }
          : entry
    )
    expect(tracePolicySummary(fields)).toBe("New traces: 25% sampled, Full payloads, Standard redaction, kept 30 days.")
  })

  it("is null when a trace field is missing", () => {
    expect(tracePolicySummary([])).toBeNull()
  })
})

describe("disabledOptionReason", () => {
  it("disables full payloads when the system allows metadata only", () => {
    const detail = field("trace.detail", { systemDefault: "metadata", systemLimit: "metadata" })
    expect(disabledOptionReason(detail, "full")).toBe(METADATA_ONLY_REASON)
    expect(disabledOptionReason(detail, "metadata")).toBeNull()
    expect(disabledOptionReason({ ...detail, systemLimit: "full", systemDefault: "full" }, "full")).toBeNull()
  })

  it("disables standard redaction when the system is strict", () => {
    const redaction = field("trace.payload_redaction", { systemLimit: "strict" })
    expect(disabledOptionReason(redaction, "standard")).toBe(STRICT_REDACTION_REASON)
    expect(disabledOptionReason(redaction, "strict")).toBeNull()
  })
})

describe("numericMax", () => {
  it("caps a numeric field at the system limit", () => {
    expect(numericMax(field("trace.retention_days", { systemLimit: 90 }), 365)).toBe(90)
    expect(numericMax(field("trace.retention_days"), 365)).toBe(365)
  })
})
