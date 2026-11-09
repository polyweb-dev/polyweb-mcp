import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { LimitHistory } from "./LimitHistory"

/**
 * UI7 history: semantic table with Time, Old balance, New balance, Source,
 * Actor; Usd one-decimal display; native fallback with unit label; actor
 * category (no invented identity); empty/load/error states; cursor paging
 * disabled while active. Covers UI7-09.
 */

function usdEvent() {
  return {
    event_id: "evt-2",
    provider: "brave",
    auth_mode: "keyed",
    operation: "search",
    pool_id: "brave:keyed:usd",
    observed_at: "2026-09-06T10:04:00Z",
    source: "local",
    reason: "local_success",
    old_native: "4.500",
    new_native: "4.495",
    old_usd: "4.5",
    new_usd: "4.495",
    debit_usd: "0.005",
    native_debit: "0.005",
    actual_usd: null,
    confidence: "observed",
    local_attempt_id: "attempt-2",
    detail: { native_unit: "USD", actor: "" },
  }
}

function grantEvent() {
  return {
    event_id: "evt-1",
    provider: "brave",
    auth_mode: "keyed",
    operation: null,
    pool_id: null,
    observed_at: "2026-09-06T10:03:00Z",
    source: "operator",
    reason: "grant",
    old_native: null,
    new_native: null,
    old_usd: null,
    new_usd: null,
    debit_usd: null,
    native_debit: null,
    actual_usd: null,
    confidence: "authoritative",
    local_attempt_id: null,
    detail: { search_granted_usd: "0.1" },
  }
}

function nativeEvent() {
  return {
    event_id: "evt-0",
    provider: "brave",
    auth_mode: "keyed",
    operation: "search",
    pool_id: "brave:keyed:usd",
    observed_at: "2026-09-06T10:02:00Z",
    source: "vendor_headers",
    reason: "vendor_sync",
    old_native: "4.500",
    new_native: "4.495",
    old_usd: null,
    new_usd: null,
    debit_usd: null,
    native_debit: null,
    actual_usd: null,
    confidence: "observed",
    local_attempt_id: null,
    detail: { native_unit: "USD" },
  }
}

describe("LimitHistory", () => {
  it.each(["USD", "CREDIT"])("shows a stored %s unit as credits", (unit) => {
    const event = { ...nativeEvent(), old_native: "1000", new_native: "900", detail: { native_unit: unit } }
    render(<LimitHistory providerName="Provider" events={[event] as never} loading={false}
      error={null} hasMore={false} onLoadMore={() => Promise.resolve()} />)
    expect(screen.getByText(unit === "USD" ? "$1,000.00" : "1,000 credits")).toBeInTheDocument()
    expect(screen.getByText(unit === "USD" ? "$900.00" : "900 credits")).toBeInTheDocument()
    expect(document.body.textContent).not.toContain("USD")
  })

  it("renders exact event facts with table headers and actor category (UI7-09)", () => {
    render(
      <LimitHistory
        providerName="Brave"
        events={[usdEvent(), grantEvent()] as never}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => Promise.resolve()}
      />,
    )
    for (const header of ["Time", "Old balance", "New balance", "Source", "Actor"]) {
      expect(screen.getByRole("columnheader", { name: header })).not.toBeNull()
    }
    expect(screen.getAllByText("$4.50")).toHaveLength(2)
    expect(screen.getAllByText("$4.50")).toHaveLength(2)
    expect(screen.getByText("System")).not.toBeNull()
    expect(screen.getByText("Operator")).not.toBeNull()
    expect(screen.getByText("Search · Local success")).not.toBeNull()
    // Polish Item 1: Source cells show human labels, not raw keys.
    expect(screen.getByText("Local usage")).not.toBeNull()
    expect(screen.getByRole("columnheader", { name: "Change" })).not.toBeNull()
    expect(screen.getByText("−$0.005")).not.toBeNull()
    expect(screen.getAllByText("Not recorded")).toHaveLength(3)
    expect(screen.queryByRole("heading", { name: "Balance history" })).toBeNull()
    expect(screen.getByText("Operator action")).not.toBeNull()
    expect(screen.queryByText("local")).toBeNull()
    expect(screen.queryByText("operator")).toBeNull()
    // Polish Item 1: rows render newest-first (evt-2 before evt-1).
    const times = Array.from(document.querySelectorAll('time[dateTime]'))
    expect(times).toHaveLength(2)
    expect(times[0].getAttribute("dateTime")).toBe("2026-09-06T10:04:00Z")
    expect(times[1].getAttribute("dateTime")).toBe("2026-09-06T10:03:00Z")
    // Polish Item 1: visible time text is locale text, not the raw ISO.
    const newestTime = document.querySelector('time[dateTime="2026-09-06T10:04:00Z"]')
    expect(newestTime?.textContent).not.toBe("2026-09-06T10:04:00Z")
  })

  it("falls back to native values with a unit label when Usd stays absent (UI7-09)", () => {
    render(
      <LimitHistory
        providerName="Brave"
        events={[nativeEvent()] as never}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => Promise.resolve()}
      />,
    )
    expect(screen.getAllByText("$4.50")[0]).not.toBeNull()
    expect(screen.getAllByText("$4.50")[1]).not.toBeNull()
  })

  it("leaves absent values empty without an Unknown row or fake zero (UI7-09)", () => {
    render(
      <LimitHistory
        providerName="Brave"
        events={[grantEvent()] as never}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => Promise.resolve()}
      />,
    )
    expect(screen.queryByText("Unknown")).toBe(null)
    expect(screen.getByRole("table")).not.toBeNull()
  })

  it("keeps the ISO timestamp in the time element (UI7-09)", () => {
    render(
      <LimitHistory
        providerName="Brave"
        events={[usdEvent()] as never}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => Promise.resolve()}
      />,
    )
    expect(document.querySelector('time[dateTime="2026-09-06T10:04:00Z"]')).not.toBeNull()
  })

  it("retains empty, load, and error states inside the modal (UI7-09)", () => {
    const { rerender } = render(
      <LimitHistory providerName="Brave" events={[]} loading={false} error={null} hasMore={false} onLoadMore={() => Promise.resolve()} />,
    )
    expect(screen.getByText("No balance change recorded yet")).not.toBeNull()
    rerender(
      <LimitHistory providerName="Brave" events={[]} loading error={null} hasMore={false} onLoadMore={() => Promise.resolve()} />,
    )
    expect(screen.getByRole("status")).not.toBeNull()
    rerender(
      <LimitHistory providerName="Brave" events={[]} loading={false} error="history unavailable" hasMore={false} onLoadMore={() => Promise.resolve()} />,
    )
    expect(screen.getByRole("alert")).not.toBeNull()
  })

  it("disables pagination during an active request (UI7-09)", async () => {
    const onLoadMore = vi.fn(() => Promise.resolve())
    render(
      <LimitHistory
        providerName="Brave"
        events={[usdEvent()] as never}
        loading
        error={null}
        hasMore
        onLoadMore={onLoadMore}
      />,
    )
    const button = screen.getByRole("button", { name: "Load older limit events for Brave" })
    expect(button.hasAttribute("disabled")).toBe(true)
    const user = userEvent.setup()
    await user.click(button).catch(() => {})
    expect(onLoadMore).not.toHaveBeenCalled()
  })
})

describe("LimitHistory Tavily native", () => {
  function tavilyProfile() {
    return {
      native_usd_per_unit: "0.008",
      cost_basis: "paygo_reference",
      price_version: "paygo-reference",
      source: "documented",
      estimated: true,
    }
  }

  function tavilyNativeEvent() {
    return {
      event_id: "evt-tavily-1",
      provider: "tavily",
      auth_mode: "keyed",
      operation: "search",
      pool_id: "tavily:keyed:credits",
      observed_at: "2026-09-06T10:04:00Z",
      source: "vendor_api",
      reason: "sync",
      old_native: "999",
      new_native: "998",
      old_usd: "7.992",
      new_usd: "7.984",
      debit_usd: "0.008",
      native_debit: "1",
      actual_usd: null,
      confidence: "observed",
      local_attempt_id: "attempt-1",
      detail: { native_unit: "CREDIT", actor: "" },
    }
  }

  function tavilyUsdOnlyEvent() {
    return {
      event_id: "evt-tavily-2",
      provider: "tavily",
      auth_mode: "keyed",
      operation: null,
      pool_id: null,
      observed_at: "2026-09-06T10:03:00Z",
      source: "operator",
      reason: "grant",
      old_native: null,
      new_native: null,
      old_usd: null,
      new_usd: null,
      debit_usd: null,
      native_debit: null,
      actual_usd: null,
      confidence: "authoritative",
      local_attempt_id: null,
      detail: { search_granted_usd: "0.008" },
    }
  }

  it("prefers native Tavily balances over Usd amounts", () => {
    render(
      <LimitHistory
        providerName="Tavily"
        events={[tavilyNativeEvent()] as never}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => Promise.resolve()}
      />,
    )
    expect(screen.getByText("999 credits")).not.toBeNull()
    expect(screen.getByText("998 credits")).not.toBeNull()
    expect(screen.queryByText("7992 Usd")).toBeNull()
  })

  it("converts Usd-only Tavily grant events through the profile", () => {
    const grant = {
      event_id: "evt-tavily-3",
      provider: "tavily",
      auth_mode: "keyed",
      operation: "search",
      pool_id: "tavily:keyed:credits",
      observed_at: "2026-09-06T10:02:00Z",
      source: "local",
      reason: "local_success",
      old_native: null,
      new_native: null,
      old_usd: "0.008",
      new_usd: "0.016",
      debit_usd: "0.008",
      native_debit: null,
      actual_usd: null,
      confidence: "observed",
      local_attempt_id: "attempt-3",
      detail: { native_unit: "CREDIT", actor: "" },
    }
    render(
      <LimitHistory
        providerName="Tavily"
        events={[grant] as never}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => Promise.resolve()}
        profile={tavilyProfile() as never}
      />,
    )
    expect(screen.getByText("1 credit")).not.toBeNull()
    expect(screen.getByText("2 credits")).not.toBeNull()
    expect(tavilyUsdOnlyEvent().event_id).toBe("evt-tavily-2")
  })

  it("converts Usd-only Tavily events through the default profile without a profile prop", () => {
    const grant = {
      event_id: "evt-tavily-4",
      provider: "tavily",
      auth_mode: "keyed",
      operation: "search",
      pool_id: "tavily:keyed:credits",
      observed_at: "2026-09-06T10:02:00Z",
      source: "local",
      reason: "local_success",
      old_native: null,
      new_native: null,
      old_usd: "0.008",
      new_usd: "0.016",
      debit_usd: "0.008",
      native_debit: null,
      actual_usd: null,
      confidence: "observed",
      local_attempt_id: "attempt-4",
      detail: { native_unit: "CREDIT", actor: "" },
    }
    render(
      <LimitHistory
        providerName="Tavily"
        events={[grant] as never}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => Promise.resolve()}
      />,
    )
    expect(screen.getByText("1 credit")).not.toBeNull()
    expect(screen.getByText("2 credits")).not.toBeNull()
  })
})
