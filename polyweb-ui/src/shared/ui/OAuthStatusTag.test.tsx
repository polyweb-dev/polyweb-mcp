import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { OAuthStatusTag } from "./OAuthStatusTag"

describe("OAuthStatusTag", () => {
  it("shows the readable refresh failure status", () => {
    render(<OAuthStatusTag status="refresh_failed" />)
    expect(screen.getByText("Refresh failed")).toBeInTheDocument()
  })

  it("shows an unavailable status without inventing a connection state", () => {
    render(<OAuthStatusTag status={null} />)
    expect(screen.getByText("Status unavailable")).toBeInTheDocument()
  })
})
