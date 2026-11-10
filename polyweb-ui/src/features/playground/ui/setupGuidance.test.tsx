import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import type { PlaygroundController } from "../model/usePlaygroundController"
import { ProviderSetupNotice } from "./ProviderSetupNotice"
import { pinnedProviderName } from "./setupGuidance"

function providerStub(id: string, name: string) {
  return { id, name, available: true, enabled: true, effectiveOperations: ["search" as const] }
}

function controllerOf(overrides: Partial<PlaygroundController> = {}): PlaygroundController {
  return {
    selectedProviderId: "auto",
    eligibleProviders: [],
    ...overrides,
  } as unknown as PlaygroundController
}

describe("pinnedProviderName (TASK-000065 AC#7/AC#8)", () => {
  it("stays unscoped for auto/all runs", () => {
    expect(pinnedProviderName(controllerOf())).toBeUndefined()
    expect(pinnedProviderName(controllerOf({ selectedProviderId: "all" }))).toBeUndefined()
  })

  it("names the pinned eligible provider", () => {
    const controller = controllerOf({
      selectedProviderId: "keenable",
      eligibleProviders: [providerStub("keenable", "Keenable"), providerStub("tavily", "Tavily")],
    })
    expect(pinnedProviderName(controller)).toBe("Keenable")
  })

  it("stays unscoped when the pinned provider is no longer eligible", () => {
    const controller = controllerOf({
      selectedProviderId: "keenable",
      eligibleProviders: [providerStub("tavily", "Tavily")],
    })
    expect(pinnedProviderName(controller)).toBeUndefined()
  })
})

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
