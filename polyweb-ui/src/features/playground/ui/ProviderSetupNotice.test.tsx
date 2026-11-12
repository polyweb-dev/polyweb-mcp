import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { ProviderSetupNotice } from "./ProviderSetupNotice"

describe("ProviderSetupNotice actionable guidance (TASK-000065 AC#1/AC#7)", () => {
  it("names pool creation or assignment without resembling a timeout", () => {
    render(
      <MemoryRouter>
        <ProviderSetupNotice projectId="project-1" />
      </MemoryRouter>
    )
    expect(screen.getByText(/No provider is set up for this project/)).toBeInTheDocument()
    expect(screen.getByText(/Create or assign a provider pool/)).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Set up providers" })).toHaveAttribute("href", "/p/project-1/providers")
    expect(screen.queryByText(/timed out|timeout/i)).toBeNull()
  })

  it("names the pinned provider pool when the run pins one", () => {
    render(
      <MemoryRouter>
        <ProviderSetupNotice projectId="project-1" providerName="Keenable" />
      </MemoryRouter>
    )
    expect(screen.getByText(/No Keenable pool is set up for this project/)).toBeInTheDocument()
    expect(screen.getByText(/Create or assign a Keenable pool/)).toBeInTheDocument()
  })
})
