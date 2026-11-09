import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { FetchResponse } from "@/domains/execution"
import { FetchResult } from "./FetchResult"

function fetchResponse(overrides: Partial<FetchResponse> = {}): FetchResponse {
  return {
    document: {
      url: "https://example.com/parity-doc",
      title: "Parity document",
      content: "# Parity\n\nBody.",
      markdown: "# Parity\n\nBody.",
      providerId: "keenable",
      // Raw wire value on purpose: the badge must resolve the catalog name.
      providerName: "keenable",
      statusCode: null,
      contentLength: 16,
      executionTimeMs: 120,
    },
    providerId: "keenable",
    fallbackChain: ["keenable"],
    costEstimateCredits: 1,
    executionTimeMs: 120,
    timestamp: "2026-09-29T00:00:00.000Z",
    ...overrides,
  }
}

/**
 * FetchResult (Item 1): the provider badge resolves the raw wire value
 * through providerIdentity, so `keenable` shows Keenable and `you` shows
 * You.com with the catalog logo. Copy keeps its markdown feedback.
 */
describe("FetchResult", () => {
  it("shows the Keenable catalog name with its logo for the raw wire value", () => {
    render(<FetchResult result={fetchResponse()} copied={false} onCopy={() => {}} />)

    expect(screen.getByText("Keenable")).toBeInTheDocument()
    expect(screen.queryByText("keenable")).not.toBeInTheDocument()
    expect(screen.getByTestId("provider-logo-keenable")).toBeInTheDocument()
  })

  it("shows the You.com catalog name with its logo for the raw you value", () => {
    render(
      <FetchResult
        result={fetchResponse({
          document: {
            url: "https://example.com/parity-doc",
            title: "Parity document",
            content: "# Parity\n\nBody.",
            markdown: "# Parity\n\nBody.",
            providerId: "youcom",
            providerName: "you",
            statusCode: null,
            contentLength: 16,
            executionTimeMs: 120,
          },
          providerId: "youcom",
          fallbackChain: ["youcom"],
        })}
        copied={false}
        onCopy={() => {}}
      />
    )

    expect(screen.getByText("You.com")).toBeInTheDocument()
    expect(screen.queryByText("you", { exact: true })).not.toBeInTheDocument()
    expect(screen.getByTestId("provider-logo-youcom")).toBeInTheDocument()
  })

  it("shows document metadata with byte length and execution time", () => {
    render(<FetchResult result={fetchResponse()} copied={false} onCopy={() => {}} />)

    expect(screen.getByText("Document metadata")).toBeInTheDocument()
    expect(screen.getByText("Parity document")).toBeInTheDocument()
    expect(screen.getByText("https://example.com/parity-doc")).toBeInTheDocument()
    expect(screen.getByText("15 bytes")).toBeInTheDocument()
    // Shared latency format ("120 ms"; the space lands with the shared formatter).
    expect(screen.getByText(/^120 ?ms$/)).toBeInTheDocument()
    expect(screen.getByText("Parsed markdown")).toBeInTheDocument()
    // The read-only source URL is a link, not an input-like box.
    expect(screen.getByRole("link", { name: "https://example.com/parity-doc" })).toHaveAttribute(
      "href",
      "https://example.com/parity-doc"
    )
    // The backend never sends an HTTP status, so no always-empty row is shown.
    expect(screen.queryByText("Status code")).not.toBeInTheDocument()
  })

  it("hands the markdown to onCopy and confirms the copied state", async () => {
    const user = userEvent.setup()
    const onCopy = vi.fn()
    const { rerender } = render(
      <FetchResult result={fetchResponse()} copied={false} onCopy={onCopy} />
    )

    await user.click(screen.getByRole("button", { name: "Copy markdown" }))
    expect(onCopy).toHaveBeenCalledTimes(1)
    expect(onCopy).toHaveBeenCalledWith("# Parity\n\nBody.")

    rerender(<FetchResult result={fetchResponse()} copied onCopy={onCopy} />)
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument()
    expect(screen.getByText(/# Parity/)).toBeInTheDocument()
  })
})
