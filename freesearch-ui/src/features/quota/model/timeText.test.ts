import { describe, expect, it } from "vitest"
import type { LimitAuditEvent } from "@/domains/dashboard"
import { dateText, newestFirst, timeText, timestampOrNull } from "./timeText"

/**
 * Polish locking suite: locale display for instants, stable calendar days,
 * and newest-first audit order. Locale-independent assertions only.
 */

function auditEvent(id: string, observedAt: string): LimitAuditEvent {
  return {
    event_id: id,
    provider: "brave",
    auth_mode: "keyed",
    operation: "search",
    pool_id: "brave:keyed:usd",
    observed_at: observedAt,
    source: "vendor_headers",
    reason: "sync",
    old_native: null,
    new_native: null,
    old_crd: null,
    new_crd: null,
    crd_debit: null,
    native_debit: null,
    actual_usd: null,
    confidence: "observed",
    local_attempt_id: null,
    detail: {},
  }
}

describe("timeText", () => {
  it("renders a valid instant in the reader locale, not as raw ISO", () => {
    const raw = "2026-09-06T10:05:00Z"
    const text = timeText(raw)
    expect(text).not.toBe(raw)
    expect(text).toContain("2026")
  })

  it("keeps an unreadable value verbatim", () => {
    expect(timeText("not-a-date")).toBe("not-a-date")
  })

  it("returns no text for a missing instant", () => {
    expect(timeText(null)).toBe("")
    expect(timeText(undefined)).toBe("")
    expect(timeText("")).toBe("")
    expect(timeText("   ")).toBe("")
  })
})

describe("dateText", () => {
  it("keeps the calendar day of a date-only value", () => {
    const expected = new Date("2026-09-30T00:00:00").toLocaleDateString()
    expect(dateText("2026-09-30")).toBe(expected)
  })

  it("returns no text for a missing date", () => {
    expect(dateText(null)).toBe("")
    expect(dateText(undefined)).toBe("")
    expect(dateText("   ")).toBe("")
  })
})

describe("timestampOrNull", () => {
  it("returns locale text for a valid instant", () => {
    const text = timestampOrNull("2026-09-06T10:05:00Z")
    expect(text).not.toBeNull()
    expect(text as string).toContain("2026")
  })

  it("returns null for a missing instant", () => {
    expect(timestampOrNull(null)).toBeNull()
    expect(timestampOrNull(undefined)).toBeNull()
    expect(timestampOrNull("   ")).toBeNull()
  })
})

describe("newestFirst", () => {
  it("orders the newest observed row first", () => {
    const first = auditEvent("a", "2026-09-01T10:00:00Z")
    const second = auditEvent("b", "2026-09-02T10:00:00Z")
    const third = auditEvent("c", "2026-09-03T10:00:00Z")
    const ordered = newestFirst([first, third, second])
    expect(ordered.map((event) => event.event_id)).toEqual(["c", "b", "a"])
  })

  it("sorts an unreadable instant last", () => {
    const readable = auditEvent("a", "2026-09-01T10:00:00Z")
    const unreadable = auditEvent("bad", "not-a-date")
    const ordered = newestFirst([unreadable, readable])
    expect(ordered.map((event) => event.event_id)).toEqual(["a", "bad"])
  })

  it("does not mutate the input list", () => {
    const first = auditEvent("a", "2026-09-01T10:00:00Z")
    const second = auditEvent("b", "2026-09-02T10:00:00Z")
    const input = [first, second]
    newestFirst(input)
    expect(input.map((event) => event.event_id)).toEqual(["a", "b"])
  })
})
