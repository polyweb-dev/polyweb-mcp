import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ProviderCardActions, type ProviderCardActionsProps } from "./ProviderCardActions"
import { formatDateTime } from "@/shared/lib/formatTime"

/**
 * Card footer controls: one Refresh button with a stable accessible name, the
 * plain result of the last refresh beside it, and the composed OAuth control.
 */

function renderActions(overrides: Partial<ProviderCardActionsProps> = {}) {
  return render(
    <ProviderCardActions
      providerName="Brave"
      syncing={false}
      onSync={() => {}}
      {...overrides}
    />,
  )
}

describe("ProviderCardActions", () => {
  it("exposes one sentence-case Refresh control with a stable name", () => {
    renderActions()
    const sync = screen.getByRole("button", { name: "Refresh limits for Brave" })
    expect(sync.textContent).toBe("Refresh")
    expect(screen.getAllByRole("button")).toHaveLength(1)
  })

  it("calls onSync on click", async () => {
    const onSync = vi.fn()
    renderActions({ onSync })
    await userEvent.setup().click(screen.getByRole("button", { name: "Refresh limits for Brave" }))
    expect(onSync).toHaveBeenCalledTimes(1)
  })

  it("disables sync and shows syncing text while syncing", () => {
    renderActions({ syncing: true })
    const sync = screen.getByRole("button", { name: "Refresh limits for Brave" })
    expect(sync.hasAttribute("disabled")).toBe(true)
    expect(sync.textContent).toBe("Refreshing…")
  })

  it("hides Refresh when the provider reports no usage", () => {
    renderActions({ refreshSkipped: true, syncNote: "This provider does not report usage" })
    expect(screen.queryByRole("button", { name: "Refresh limits for Brave" })).toBeNull()
    expect(screen.getByRole("status").textContent).toBe("This provider does not report usage")
  })

  it("shows the refresh result next to the Refresh control", () => {
    const updatedAt = Date.parse("2026-11-08T10:00:00Z")
    renderActions({ syncNote: "Updated just now", updatedAt })
    const note = screen.getByRole("status")
    expect(note.textContent).toBe("Updated just now")
    expect(note.title).toBe(formatDateTime("2026-11-08T10:00:00Z"))
    const sync = screen.getByRole("button", { name: "Refresh limits for Brave" })
    expect(sync.parentElement).toBe(note.parentElement)
  })

  it("shows no status line before the first refresh", () => {
    renderActions()
    expect(screen.queryByRole("status")).toBeNull()
  })

  it("renders the composed OAuth control inline after Refresh", () => {
    renderActions({
      providerName: "Parallel",
      oauthActions: (
        <button type="button" data-testid="oauth-device-open-parallel">
          Connect
        </button>
      ),
    })
    const connect = screen.getByTestId("oauth-device-open-parallel")
    const row = connect.closest("div.flex.flex-wrap")
    expect(row?.textContent).toContain("Refresh")
    const labels = screen.getAllByRole("button").map((button) => button.textContent)
    expect(labels).toEqual(["Refresh", "Connect"])
  })
})
