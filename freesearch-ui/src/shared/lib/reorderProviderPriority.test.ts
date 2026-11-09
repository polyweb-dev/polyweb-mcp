import { describe, expect, it } from "vitest"
import { reorderProviderPriority } from "./reorderProviderPriority"

describe("reorderProviderPriority", () => {
  it("moves an item without changing the original list", () => {
    const ids = ["a", "b", "c"]
    expect(reorderProviderPriority(ids, "c", "a")).toEqual(["c", "a", "b"])
    expect(ids).toEqual(["a", "b", "c"])
  })

  it("ignores an unchanged or unknown position", () => {
    expect(reorderProviderPriority(["a", "b"], "a", "a")).toEqual(["a", "b"])
    expect(reorderProviderPriority(["a", "b"], "a", "missing")).toEqual(["a", "b"])
  })
})
