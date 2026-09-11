import { describe, it, expect } from "vitest"
import { ApiError, parseDetail, statusMessage } from "@/shared/api/http"

/**
 * RED: `src/services/api/httpErrors.ts` does not exist yet. The Developer
 * creates it with:
 * - `class ApiError extends Error { status; detail; raw }`
 * - `parseDetail(body)` — string detail → as-is; {detail:[{loc,msg}]} →
 *   joined "loc: msg"; else short JSON
 * - `statusMessage(status, detail)` — user-facing mapping for
 *   404/422/503/500/0 including "API unreachable" + proxy hint.
 */

describe("ApiError", () => {
  it("carries status, detail, and raw payload and behaves as an Error", () => {
    const raw = { detail: "unknown provider 'nope'" }
    const error = new ApiError(404, "unknown provider 'nope'", raw)

    expect(error).toBeInstanceOf(Error)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.name).toBe("ApiError")
    expect(error.status).toBe(404)
    expect(error.detail).toBe("unknown provider 'nope'")
    expect(error.raw).toBe(raw)
    expect(error.message).toContain("unknown provider 'nope'")
  })

  it("represents network failures with status 0", () => {
    const cause = new TypeError("fetch failed")
    const error = new ApiError(0, "API unreachable", cause)

    expect(error.status).toBe(0)
    expect(error.detail).toBe("API unreachable")
    expect(error.raw).toBe(cause)
  })
})

describe("parseDetail", () => {
  it("returns a string detail body as-is", () => {
    expect(parseDetail({ detail: "unknown provider 'nope'" })).toBe(
      "unknown provider 'nope'"
    )
  })

  it("joins FastAPI 422 item loc and msg as 'loc: msg'", () => {
    expect(
      parseDetail({ detail: [{ loc: ["body", "query"], msg: "Field required" }] })
    ).toBe("body.query: Field required")
  })

  it("joins multiple 422 items with '; '", () => {
    expect(
      parseDetail({
        detail: [
          { loc: ["body", "query"], msg: "Field required" },
          { loc: ["body", "limit"], msg: "Input should be less than or equal to 100" },
        ],
      })
    ).toBe(
      "body.query: Field required; body.limit: Input should be less than or equal to 100"
    )
  })

  it("falls back to short JSON for unknown shapes", () => {
    expect(parseDetail({ unexpected: 1 })).toBe('{"unexpected":1}')
  })

  it("always returns a non-empty string for empty bodies", () => {
    expect(typeof parseDetail(undefined)).toBe("string")
    expect(parseDetail(undefined).length).toBeGreaterThan(0)
    expect(typeof parseDetail(null)).toBe("string")
    expect(parseDetail(null).length).toBeGreaterThan(0)
  })
})

describe("statusMessage", () => {
  it("maps network failure (0) to API-unreachable copy with a proxy hint", () => {
    const message = statusMessage(0, "fetch failed")

    expect(message).toContain("API unreachable")
    expect(message).toMatch(/proxy/i)
  })

  it("maps 404 to a not-found message preserving the detail", () => {
    const message = statusMessage(404, "unknown provider 'nope'")

    expect(message).toMatch(/not found/i)
    expect(message).toContain("unknown provider 'nope'")
  })

  it("maps 422 to an invalid-request message preserving the detail", () => {
    const message = statusMessage(422, "body.query: Field required")

    expect(message).toMatch(/invalid/i)
    expect(message).toContain("body.query: Field required")
  })

  it("maps 503 to a temporarily-unavailable message preserving the detail", () => {
    const message = statusMessage(503, "provider brave is disabled")

    expect(message).toMatch(/unavailable|try again/i)
    expect(message).toContain("provider brave is disabled")
  })

  it("maps 500 to a server-error message preserving the detail", () => {
    const message = statusMessage(500, "adapter exploded")

    expect(message).toMatch(/server error/i)
    expect(message).toContain("adapter exploded")
  })

  it("maps abort/timeout failures to a timeout message, not API-unreachable", () => {
    const message = statusMessage(0, "The operation was aborted due to timeout")

    expect(message).toMatch(/timed out|timeout/i)
    expect(message).not.toMatch(/unreachable/i)
  })
})
