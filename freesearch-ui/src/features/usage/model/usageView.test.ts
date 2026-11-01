import { describe, expect, it } from "vitest"
import { usageLatencyText, usageProviderLabel, usageTimeText } from "./usageView"

describe("usageView", () => {
  it("labels wire provider ids with their catalog names", () => {
    expect(usageProviderLabel("you")).toBe("You.com")
    expect(usageProviderLabel("brave")).toBe("Brave Search")
    expect(usageProviderLabel("unknown-provider")).toBe("unknown-provider")
  })

  it("shows latency in milliseconds and a dash when unmeasured", () => {
    expect(usageLatencyText(209.6)).toBe("210 ms")
    expect(usageLatencyText(null)).toBe("—")
  })

  it("keeps an unparseable timestamp as its raw text", () => {
    expect(usageTimeText("not-a-date")).toBe("not-a-date")
    expect(usageTimeText("2026-10-30T10:00:00Z")).toBe(new Date("2026-10-30T10:00:00Z").toLocaleString())
  })
})
