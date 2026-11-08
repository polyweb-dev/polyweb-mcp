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
  expect(formatPoolRate({ limit: null, window_seconds: 60 }, { search: 30, fetch: 10 })).toBe("Search 30, Fetch 10 per minute")
})
