import { describe, expect, it } from "vitest"
import { filtersFromSearch, filtersToSearch } from "./activityFilters"

describe("activityFilters", () => {
  it("reads known operation and outcome values from the query", () => {
    expect(filtersFromSearch(new URLSearchParams("operation=fetch&outcome=partial"))).toEqual({
      operation: "fetch",
      outcome: "partial",
    })
  })

  it("reads a missing or unknown value as every value", () => {
    expect(filtersFromSearch(new URLSearchParams("operation=answer&outcome="))).toEqual({
      operation: null,
      outcome: null,
    })
  })

  it("writes the filters, omits every-value filters, and keeps other params", () => {
    const next = filtersToSearch(new URLSearchParams("operation=fetch&keep=1"), {
      operation: null,
      outcome: "error",
    })
    expect(next.toString()).toBe("keep=1&outcome=error")
  })
})
