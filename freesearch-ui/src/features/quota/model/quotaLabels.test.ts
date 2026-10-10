import { describe, expect, it } from "vitest"
import {
  BALANCE_ENTRY,
  BALANCE_ENTRY_NOTE,
  CONTROL_SPLIT_NOTE,
  SPEND_CAP,
  SPEND_CAP_NOTE,
  operationLabel,
  poolName,
  reasonLabel,
  sourceLabel,
} from "./quotaLabels"

/**
 * Polish locking suite: one name per control, source, reason, pool, and
 * operation. Verbatim copies of the production strings keep a rename visible.
 */

describe("quotaLabels controls", () => {
  it("keeps the balance entry control name exact", () => {
    expect(BALANCE_ENTRY).toBe("Provider Balance")
  })

  it("keeps the spend cap control name exact", () => {
    expect(SPEND_CAP).toBe("Budget Limit")
  })

  it("keeps the balance entry note exact", () => {
    expect(BALANCE_ENTRY_NOTE).toBe("Records the balance the vendor dashboard shows, as an estimate.")
  })

  it("keeps the spend cap note exact", () => {
    expect(SPEND_CAP_NOTE).toBe("Sets a local credit-unit ceiling that adds no vendor funds.")
  })

  it("states both controls in the split note", () => {
    expect(CONTROL_SPLIT_NOTE).toContain(BALANCE_ENTRY)
    expect(CONTROL_SPLIT_NOTE).toContain(SPEND_CAP)
  })

  it("keeps the split note exact", () => {
    expect(CONTROL_SPLIT_NOTE).toBe(
      "Provider Balance records the vendor dashboard balance as an estimate. Budget Limit sets a local credit-unit ceiling.",
    )
  })
})

describe("quotaLabels sourceLabel", () => {
  it("labels every documented source key", () => {
    expect(sourceLabel("documented")).toBe("Documented price")
    expect(sourceLabel("local")).toBe("Local use")
    expect(sourceLabel("local_daily_estimate")).toBe("Daily estimate (UTC)")
    expect(sourceLabel("local_ledger")).toBe("Local ledger")
    expect(sourceLabel("manual_anchor")).toBe("Provider Balance")
  })

  it("labels every operator and vendor source key", () => {
    expect(sourceLabel("operator")).toBe("Operator action")
    expect(sourceLabel("operator_grant")).toBe("Budget Limit")
    expect(sourceLabel("vendor_api")).toBe("Vendor API")
    expect(sourceLabel("vendor_headers")).toBe("Vendor headers")
  })

  it("returns no text for an absent source", () => {
    expect(sourceLabel("")).toBe("")
    expect(sourceLabel("unknown")).toBe("")
    expect(sourceLabel("n/a")).toBe("")
    expect(sourceLabel("none")).toBe("")
    expect(sourceLabel(null)).toBe("")
    expect(sourceLabel(undefined)).toBe("")
  })

  it("falls back to sentence case for an unknown key", () => {
    expect(sourceLabel("future_key")).toBe("Future key")
  })
})

describe("quotaLabels reasonLabel", () => {
  it("labels the spend cap reason", () => {
    expect(reasonLabel("grant")).toBe("Budget Limit")
  })

  it("labels the balance entry reason", () => {
    expect(reasonLabel("manual_anchor")).toBe("Provider Balance")
  })

  it("returns no text for an absent reason", () => {
    expect(reasonLabel("")).toBe("")
    expect(reasonLabel("unknown")).toBe("")
    expect(reasonLabel(null)).toBe("")
    expect(reasonLabel(undefined)).toBe("")
  })

  it("falls back to sentence case for an unknown reason", () => {
    expect(reasonLabel("custom_reason")).toBe("Custom reason")
  })
})

describe("quotaLabels poolName", () => {
  it("names the Brave keyed USD pool", () => {
    expect(poolName("brave:keyed:usd")).toBe("Keyed USD")
  })

  it("matches the unit without regard to case", () => {
    expect(poolName("brave:keyed:USD")).toBe("Keyed USD")
  })

  it("falls back to the raw key when the pool id has no three parts", () => {
    expect(poolName("brave:keyed")).toBe("Brave keyed")
  })

  it("returns no text for a missing pool id", () => {
    expect(poolName(null)).toBe("")
    expect(poolName(undefined)).toBe("")
    expect(poolName("")).toBe("")
    expect(poolName("   ")).toBe("")
  })
})

describe("quotaLabels operationLabel", () => {
  it("labels search and fetch operations", () => {
    expect(operationLabel("search")).toBe("Search")
    expect(operationLabel("fetch")).toBe("Fetch")
  })

  it("falls back to sentence case for an unknown operation", () => {
    expect(operationLabel("embed")).toBe("Embed")
  })

  it("returns no text for a missing operation", () => {
    expect(operationLabel(null)).toBe("")
    expect(operationLabel(undefined)).toBe("")
    expect(operationLabel("")).toBe("")
    expect(operationLabel("   ")).toBe("")
  })
})
