import { expect, it } from "vitest"
import { defaultPoolOperations, formatPoolRate, hasAllowedOperations } from "../index"

it("defaults to supported operations and rejects an empty selection", () => {
  expect(defaultPoolOperations(["fetch", "unknown", "search"])).toEqual(["search", "fetch"])
  expect(hasAllowedOperations([])).toBe(false)
  expect(hasAllowedOperations(["fetch"])).toBe(true)
})

it("formats shared and per-operation rates", () => {
  expect(formatPoolRate({ limit: null, window_seconds: 60 })).toBe("No limit")
  expect(formatPoolRate({ limit: 60, window_seconds: 60 })).toBe("60 per minute")
  expect(formatPoolRate({ limit: null, window_seconds: 60 }, { operationLimits: { search: 30, fetch: 10 } })).toBe("Search 30, Fetch 10 per minute")
})

it("formats dense rates for named and custom windows without changing unlimited rates", () => {
  expect(formatPoolRate({ limit: 60, window_seconds: 60 }, { short: true })).toBe("60/min")
  expect(formatPoolRate({ limit: 5, window_seconds: 1 }, { short: true })).toBe("5/s")
  expect(formatPoolRate({ limit: 12, window_seconds: 3600 }, { short: true })).toBe("12/h")
  expect(formatPoolRate({ limit: 5, window_seconds: 30 }, { short: true })).toBe("5/30s")
  expect(formatPoolRate({ limit: null, window_seconds: 60 }, { short: true })).toBe("No limit")
  expect(formatPoolRate({ limit: null, window_seconds: 60 }, { short: true, operationLimits: { fetch: 10, search: 30 } })).toBe("Search 30, Fetch 10/min")
})
