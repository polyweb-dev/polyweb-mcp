import { describe, expect, it } from "vitest"
import { usageProviderLabel } from "./usageView"

describe("usageView", () => {
  it("labels wire provider ids with their catalog names", () => {
    expect(usageProviderLabel("you")).toBe("You.com")
    expect(usageProviderLabel("brave")).toBe("Brave Search")
    expect(usageProviderLabel("unknown-provider")).toBe("unknown-provider")
  })
})
