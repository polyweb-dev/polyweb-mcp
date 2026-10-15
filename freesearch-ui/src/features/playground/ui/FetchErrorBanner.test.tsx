import React from "react"
import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { FetchErrorBanner } from "./FetchErrorBanner"

describe("FetchErrorBanner", () => {
  it("renders bot blocked error state", () => {
    render(<FetchErrorBanner error="tinyfish: bot_blocked: target site blocked automated bot access" />)

    expect(screen.getByRole("alert")).toBeInTheDocument()
    expect(screen.getByText("Target Site Access Blocked")).toBeInTheDocument()
    expect(
      screen.getByText(/target site \(e\.g\., LinkedIn\) restricts automated bots/i)
    ).toBeInTheDocument()
    expect(
      screen.getByText("tinyfish: bot_blocked: target site blocked automated bot access")
    ).toBeInTheDocument()
  })

  it("renders 403 access denied as bot blocked", () => {
    render(<FetchErrorBanner error="firecrawl: http_error: HTTP 403 access denied" />)

    expect(screen.getByText("Target Site Access Blocked")).toBeInTheDocument()
  })

  it("renders timeout error state", () => {
    render(<FetchErrorBanner error="Request timed out; please try again" />)

    expect(screen.getByText("Fetch Request Timed Out")).toBeInTheDocument()
    expect(
      screen.getByText(/did not respond within 15 seconds/i)
    ).toBeInTheDocument()
  })

  it("renders quota exhausted error state", () => {
    render(<FetchErrorBanner error="tavily: quota_exhausted: out of credits" />)

    expect(screen.getByText("Provider Quota Exhausted")).toBeInTheDocument()
    expect(
      screen.getByText(/no remaining credits.*Settings > Quotas/i)
    ).toBeInTheDocument()
  })

  it("renders general failure fallback state", () => {
    render(<FetchErrorBanner error="provider: fetch_failed: unknown error" />)

    expect(screen.getByText("Document Fetch Failed")).toBeInTheDocument()
    expect(
      screen.getByText(/unable to extract readable content/i)
    ).toBeInTheDocument()
    expect(screen.getByText("provider: fetch_failed: unknown error")).toBeInTheDocument()
  })
})
