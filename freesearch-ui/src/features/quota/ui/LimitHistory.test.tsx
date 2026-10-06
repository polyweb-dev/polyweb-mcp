import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { LimitHistory } from "./LimitHistory"

/**
 * UI7 history: semantic table with Time, Old balance, New balance, Source,
 * Actor; CRD one-decimal display; native fallback with unit label; actor
 * category (no invented identity); empty/load/error states; cursor paging
 * disabled while active. Covers UI7-09.
 */

function crdEvent() {
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
    old_crd: "4500",
    new_crd: "4495",
    crd_debit: "5",
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
    old_crd: null,
    new_crd: null,
    crd_debit: null,
    native_debit: null,
    actual_usd: null,
    confidence: "authoritative",
    local_attempt_id: null,
    detail: { search_granted_crd: "100" },
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
    old_crd: null,
    new_crd: null,
    crd_debit: null,
    native_debit: null,
    actual_usd: null,
    confidence: "observed",
    local_attempt_id: null,
    detail: { native_unit: "USD" },
  }
}

describe("LimitHistory", () => {
  it("renders exact event facts with table headers and actor category (UI7-09)", () => {
    render(
      <LimitHistory
        providerName="Brave"
        events={[crdEvent(), grantEvent()] as never}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => Promise.resolve()}
      />,
    )
    for (const header of ["Time", "Old balance", "New balance", "Source", "Actor"]) {
      expect(screen.getByRole("columnheader", { name: header })).not.toBeNull()
    }
    expect(screen.getByText("4500 CRD")).not.toBeNull()
    expect(screen.getByText("4495 CRD")).not.toBeNull()
    expect(screen.getByText("System")).not.toBeNull()
    expect(screen.getByText("Operator")).not.toBeNull()
    expect(screen.getByText("Search · Local success")).not.toBeNull()
    // Polish Item 1: Source cells show human labels, not raw keys.
    expect(screen.getByText("Local use")).not.toBeNull()
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

  it("falls back to native values with a unit label when CRD stays absent (UI7-09)", () => {
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
    expect(screen.getByText("4.500 USD")).not.toBeNull()
    expect(screen.getByText("4.495 USD")).not.toBeNull()
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
        events={[crdEvent()] as never}
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
    expect(screen.getByText("No balance change recorded yet.")).not.toBeNull()
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
        events={[crdEvent()] as never}
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
