import { describe, expect, it } from "vitest"
import { isTraceId, searchTraceRef } from "./traceId"

const TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"

describe("isTraceId", () => {
  it("accepts 32 lowercase hex characters", () => {
    expect(isTraceId(TRACE_ID)).toBe(true)
  })

  it.each([["", ""], ["uppercase", TRACE_ID.toUpperCase()], ["short", TRACE_ID.slice(0, 16)], ["padded", ` ${TRACE_ID}`], ["number", 42], ["null", null]])(
    "rejects %s",
    (_label, value) => {
      expect(isTraceId(value)).toBe(false)
    }
  )
})

describe("searchTraceRef", () => {
  it("links a well-formed trace id", () => {
    expect(searchTraceRef({ traceId: TRACE_ID })).toEqual({ traceId: TRACE_ID })
  })

  it("names a result saved before trace links as not_saved", () => {
    expect(searchTraceRef({})).toEqual({ traceId: null, reason: "not_saved" })
  })

  it.each([["null", null], ["empty", ""], ["malformed", "abc"]])("names a %s id as not_recorded", (_label, traceId) => {
    expect(searchTraceRef({ traceId })).toEqual({ traceId: null, reason: "not_recorded" })
  })
})
