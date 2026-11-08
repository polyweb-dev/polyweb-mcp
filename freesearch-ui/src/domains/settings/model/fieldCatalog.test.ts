import { describe, expect, it } from "vitest"
import { FIELD_SPECS, fieldLabel, formatSettingsValue } from "./fieldCatalog"

describe("field catalog", () => {
  it("labels the editable fields per the contract", () => {
    expect(Object.fromEntries(Object.entries(FIELD_SPECS).map(([id, spec]) => [id, spec.label]))).toEqual({
      "routing.fallback_policy": "Fallback policy",
      "routing.cost_optimization_preset": "Cost preset",
      "routing.max_attempts": "Max attempts",
      "routing.preferred_providers": "Preferred providers",
      "execution.cache_enabled": "Cache",
      "execution.default_timeout_seconds": "Timeout (seconds)",
      "execution.max_fanout_concurrency": "Fan-out concurrency",
      "execution.cache_ttl_seconds": "Cache lifetime (seconds)",
      "trace.detail": "Payload detail",
      "trace.retention_days": "Retention",
    })
    expect(fieldLabel("system.max_timeout_seconds")).toBe("system.max_timeout_seconds")
  })

  it("formats values", () => {
    expect(formatSettingsValue("trace.detail", "metadata")).toBe("Metadata only")
    expect(formatSettingsValue("execution.cache_enabled", false)).toBe("Off")
    expect(formatSettingsValue("routing.preferred_providers", [])).toBe("None")
    expect(formatSettingsValue("routing.preferred_providers", ["tavily", "exa"])).toBe("tavily, exa")
    expect(formatSettingsValue("trace.retention_days", 30)).toBe("30")
    expect(formatSettingsValue("trace.retention_days", null)).toBe("Keep all traces")
  })
})
