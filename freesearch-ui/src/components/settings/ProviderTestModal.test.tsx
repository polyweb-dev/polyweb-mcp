import { render, screen, within } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { mapProviderRows } from "@/domains/providers/model/providerMapping"
import { providerStatus } from "@/test/backendFixtures"
import { formatDateTime } from "@/shared/lib/formatTime"
import { ProviderTestModal } from "./ProviderTestModal"

const provider = mapProviderRows([providerStatus("brave")])[0] ?? null
const now = Date.parse("2026-11-08T11:00:00Z")
const props = { provider, now, testing: false, onTest: vi.fn(), onClose: vi.fn() }

describe("ProviderTestModal", () => {
  it("names the provider with its logo and keeps an absent probe separate from call health", () => {
    render(<ProviderTestModal {...props} />)
    const dialog = screen.getByRole("dialog", { name: "Test Brave Search" })
    expect(within(dialog).getByTestId("provider-logo-brave")).toBeInTheDocument()
    expect(within(dialog).getByText("Last test")).toBeInTheDocument()
    expect(within(dialog).getByText("—")).toBeInTheDocument()
    expect(within(dialog).queryByText("Last result")).toBeNull()
  })

  it("shows a relative probe time with the exact timestamp on hover", () => {
    const checkedAt = now - 300_000
    render(<ProviderTestModal {...props} lastResult={{ checkedAt, success: true, latencyMs: 1531, message: "" }} />)
    expect(screen.getByText("Healthy · 1,531 ms · 5 min ago")).toHaveAttribute("title", formatDateTime(new Date(checkedAt).toISOString()))
  })
})
