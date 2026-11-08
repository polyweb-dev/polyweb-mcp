import { describe, expect, it } from "vitest"
import {
  PREFERRED_PROVIDER_OPTIONS,
  providerLabel,
  providerLogoId,
  valueText,
} from "./settingsFormat"

describe("settingsFormat", () => {
  it("shows the keep-all retention value", () => {
    expect(valueText("trace.retention_days", null)).toBe("Keep all traces")
  })

  it("shows provider names", () => {
    expect(valueText("routing.preferred_providers", ["tavily", "you"])).toBe("Tavily, You.com")
    expect(valueText("routing.preferred_providers", [])).toBe("None")
    expect(valueText("routing.max_attempts", 3)).toBe("3")
  })

  it("offers every catalog provider by its wire id with the logo id", () => {
    expect(PREFERRED_PROVIDER_OPTIONS.map((option) => option.value)).toContain("you")
    expect(providerLabel("brave")).toBe("Brave Search")
    expect(providerLabel("unknown")).toBe("unknown")
    expect(providerLogoId("you")).toBe("youcom")
  })
})
