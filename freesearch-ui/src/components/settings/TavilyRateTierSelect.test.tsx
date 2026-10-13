import React from "react"
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { TavilyRateTierSelect } from "./TavilyRateTierSelect"
import { apiService } from "@/services/api/freesearchApi"
import type { ProviderConfig } from "@/domains/providers"

vi.mock("@/services/api/freesearchApi", () => ({
  apiService: { patchProvider: vi.fn() },
}))

/**
 * Tavily-only rate-tier dropdown (PLAN 5.2): one native select edits the
 * confirmed `tavily_key_environment` through one partial PATCH. The control
 * declares the stored key environment, never a vendor-plan upgrade, and never
 * calls vendor usage, provider-test, or force-sync endpoints.
 */

function provider(overrides: Partial<ProviderConfig> = {}): ProviderConfig {
  return {
    id: "tavily",
    name: "Tavily",
    description: "AI-native search engine.",
    baseUrl: "https://api.tavily.com",
    isCustom: false,
    capabilities: ["search", "fetch"],
    enableMask: 7,
    supportMask: 7,
    globalEnabled: true,
    searchEnabled: true,
    fetchEnabled: true,
    priority: 3,
    healthStatus: "healthy",
    circuitBreaker: "closed",
    consecutiveFailures: 0,
    latencyP95Ms: 130,
    hasKey: true,
    keyMasked: "—",
    keyVaultStatus: "configured",
    tavilyKeyEnvironment: "dev",
    quota: {
      used: null,
      limit: null,
      unit: "units",
      confidence: "estimated",
      resetPeriod: null,
      nextReset: null,
      remaining: null,
      remainingPercent: null,
      unitKind: null,
      displayUnit: null,
      observedAt: null,
      window: null,
    },
    ...overrides,
  } as ProviderConfig
}

function patchMock() {
  return vi.mocked(apiService.patchProvider)
}

beforeEach(() => {
  patchMock().mockReset()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("TavilyRateTierSelect", () => {
  it("exposes the native select with the visible label and the accessible name", () => {
    render(
      <TavilyRateTierSelect provider={provider()} canEdit onUpdated={vi.fn()} />
    )
    expect(screen.getByText("Rate tier (key environment)", { exact: true })).toBeInTheDocument()
    expect(
      screen.getByRole("combobox", { name: "Tavily rate tier (key environment)", exact: true })
    ).toBeInTheDocument()
  })

  it("offers dev and prod options with the 100 and 1000 request texts", () => {
    render(
      <TavilyRateTierSelect provider={provider()} canEdit onUpdated={vi.fn()} />
    )
    const select = screen.getByRole("combobox", {
      name: "Tavily rate tier (key environment)",
      exact: true,
    })
    expect(select.tagName).toBe("SELECT")
    const options = Array.from(select.querySelectorAll("option"))
    expect(options.map((o) => o.getAttribute("value"))).toEqual(["dev", "prod"])
    expect(options.map((o) => o.textContent)).toEqual([
      "Development — 100 requests per minute",
      "Production — 1000 requests per minute",
    ])
  })

  it("explains that the choice declares the key environment, not a vendor-plan upgrade", () => {
    const { container } = render(
      <TavilyRateTierSelect provider={provider()} canEdit onUpdated={vi.fn()} />
    )
    const titled = container.querySelector("[title]")
    expect(titled?.getAttribute("title")).toContain(
      "Declares the current key environment of the stored Tavily key, not a vendor-plan upgrade."
    )
  })

  it("submits one partial PATCH with only tavily_key_environment on a changed selection", async () => {
    const user = userEvent.setup()
    const onUpdated = vi.fn().mockResolvedValue(undefined)
    patchMock().mockResolvedValue({ tavily_key_environment: "prod" } as never)
    render(<TavilyRateTierSelect provider={provider()} canEdit onUpdated={onUpdated} />)

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Tavily rate tier (key environment)", exact: true }),
      "prod"
    )

    await waitFor(() => {
      expect(patchMock()).toHaveBeenCalledTimes(1)
    })
    expect(patchMock()).toHaveBeenCalledWith("tavily", { tavily_key_environment: "prod" })
    await waitFor(() => {
      expect(
        screen.getByRole("combobox", { name: "Tavily rate tier (key environment)", exact: true })
      ).toHaveValue("prod")
    })
    expect(onUpdated).toHaveBeenCalledTimes(1)
  })

  it("sends zero PATCHes for an unchanged selection", async () => {
    const user = userEvent.setup()
    const onUpdated = vi.fn().mockResolvedValue(undefined)
    render(<TavilyRateTierSelect provider={provider()} canEdit onUpdated={onUpdated} />)

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Tavily rate tier (key environment)", exact: true }),
      "dev"
    )

    expect(patchMock()).not.toHaveBeenCalled()
    expect(onUpdated).not.toHaveBeenCalled()
  })

  it("disables the select while the PATCH is pending and re-enables after success", async () => {
    const user = userEvent.setup()
    let resolvePatch!: (value: unknown) => void
    patchMock().mockImplementation(
      () => new Promise((resolve) => { resolvePatch = resolve as (value: unknown) => void })
    )
    const onUpdated = vi.fn().mockResolvedValue(undefined)
    render(<TavilyRateTierSelect provider={provider()} canEdit onUpdated={onUpdated} />)

    const select = screen.getByRole("combobox", {
      name: "Tavily rate tier (key environment)",
      exact: true,
    })
    await user.selectOptions(select, "prod")
    await waitFor(() => {
      expect(
        screen.getByRole("combobox", { name: "Tavily rate tier (key environment)", exact: true })
      ).toBeDisabled()
    })

    resolvePatch({ tavily_key_environment: "prod" })
    await waitFor(() => {
      expect(
        screen.getByRole("combobox", { name: "Tavily rate tier (key environment)", exact: true })
      ).not.toBeDisabled()
    })
    await waitFor(() => {
      expect(
        screen.getByRole("combobox", { name: "Tavily rate tier (key environment)", exact: true })
      ).toHaveValue("prod")
    })
  })

  it("shows an inline error and keeps the previous value after a PATCH rejection", async () => {
    const user = userEvent.setup()
    patchMock().mockRejectedValue(new Error("db down"))
    const onUpdated = vi.fn().mockResolvedValue(undefined)
    render(<TavilyRateTierSelect provider={provider()} canEdit onUpdated={onUpdated} />)

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Tavily rate tier (key environment)", exact: true }),
      "prod"
    )

    const alert = await screen.findByRole("alert")
    expect(alert.textContent).toContain("db down")
    expect(
      screen.getByRole("combobox", { name: "Tavily rate tier (key environment)", exact: true })
    ).toHaveValue("dev")
    expect(onUpdated).not.toHaveBeenCalled()
  })

  it("keeps the confirmed save when the post-save refresh fails", async () => {
    const user = userEvent.setup()
    patchMock().mockResolvedValue({ tavily_key_environment: "prod" } as never)
    const onUpdated = vi.fn().mockRejectedValue(new Error("dashboard down"))
    render(<TavilyRateTierSelect provider={provider()} canEdit onUpdated={onUpdated} />)

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Tavily rate tier (key environment)", exact: true }),
      "prod"
    )

    await waitFor(() => {
      expect(
        screen.getByRole("combobox", { name: "Tavily rate tier (key environment)", exact: true })
      ).toHaveValue("prod")
    })
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
    expect(onUpdated).toHaveBeenCalledTimes(1)
  })

  it("locks to Confirmation unavailable when the PATCH readback is absent", async () => {
    const user = userEvent.setup()
    patchMock().mockResolvedValue({} as never)
    const onUpdated = vi.fn().mockResolvedValue(undefined)
    render(<TavilyRateTierSelect provider={provider()} canEdit onUpdated={onUpdated} />)

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Tavily rate tier (key environment)", exact: true }),
      "prod"
    )

    await screen.findByText("Confirmation unavailable", { exact: true })
    await waitFor(() => {
      expect(
        screen.getByRole("combobox", { name: "Tavily rate tier (key environment)", exact: true })
      ).toBeDisabled()
    })
    expect(patchMock()).toHaveBeenCalledTimes(1)
  })

  it("never writes state after the control unmounts before the PATCH settles", async () => {
    const user = userEvent.setup()
    let resolvePatch!: (value: unknown) => void
    patchMock().mockImplementation(
      () => new Promise((resolve) => { resolvePatch = resolve as (value: unknown) => void })
    )
    const onUpdated = vi.fn().mockResolvedValue(undefined)
    const { unmount } = render(
      <TavilyRateTierSelect provider={provider()} canEdit onUpdated={onUpdated} />
    )

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Tavily rate tier (key environment)", exact: true }),
      "prod"
    )
    unmount()
    resolvePatch({ tavily_key_environment: "prod" })
    await new Promise((resolve) => setTimeout(resolve, 20))

    expect(onUpdated).not.toHaveBeenCalled()
  })

  it("supports keyboard access through focus and option selection", async () => {
    const user = userEvent.setup()
    patchMock().mockResolvedValue({ tavily_key_environment: "prod" } as never)
    const onUpdated = vi.fn().mockResolvedValue(undefined)
    render(<TavilyRateTierSelect provider={provider()} canEdit onUpdated={onUpdated} />)

    const select = screen.getByRole("combobox", {
      name: "Tavily rate tier (key environment)",
      exact: true,
    })
    await user.click(select)
    expect(select).toHaveFocus()
    await user.selectOptions(select, "prod")
    await waitFor(() => {
      expect(patchMock()).toHaveBeenCalledTimes(1)
    })
  })

  it("shows Unknown and disables changes when the status supplies no value", () => {
    render(
      <TavilyRateTierSelect
        provider={provider({ tavilyKeyEnvironment: null })}
        canEdit
        onUpdated={vi.fn()}
      />
    )
    const select = screen.getByRole("combobox", {
      name: "Tavily rate tier (key environment)",
      exact: true,
    })
    expect(select).toHaveValue("unknown")
    expect(select).toBeDisabled()
    expect(select.querySelector('option[value="unknown"]')).not.toBeNull()
  })

  it("shows Unknown when the status value is absent after an invalid readback narrows to null", () => {
    // Invalid wire values never reach this control: mergeProviderStatus narrows
    // any raw value outside dev/prod to null, so the control only sees null.
    render(
      <TavilyRateTierSelect
        provider={provider({ tavilyKeyEnvironment: null })}
        canEdit
        onUpdated={vi.fn()}
      />
    )
    expect(
      screen.getByRole("combobox", { name: "Tavily rate tier (key environment)", exact: true })
    ).toHaveValue("unknown")
    expect(patchMock()).not.toHaveBeenCalled()
  })

  it("shows keyless text with no select when no key is configured", () => {
    render(
      <TavilyRateTierSelect
        provider={provider({ keyVaultStatus: "keyless_public", hasKey: false })}
        canEdit
        onUpdated={vi.fn()}
      />
    )
    expect(screen.getByText("Keyless — numeric rate unknown", { exact: true })).toBeInTheDocument()
    expect(
      screen.queryByRole("combobox", { name: "Tavily rate tier (key environment)", exact: true })
    ).not.toBeInTheDocument()
    expect(patchMock()).not.toHaveBeenCalled()
  })

  it("shows the stored environment as read-only text for roles without edit access", () => {
    const { rerender } = render(
      <TavilyRateTierSelect provider={provider()} canEdit={false} onUpdated={vi.fn()} />
    )
    expect(screen.getByText("Development — 100 requests per minute", { exact: true })).toBeInTheDocument()
    expect(
      screen.queryByRole("combobox", { name: "Tavily rate tier (key environment)", exact: true })
    ).not.toBeInTheDocument()

    rerender(
      <TavilyRateTierSelect
        provider={provider({ tavilyKeyEnvironment: "prod" })}
        canEdit={false}
        onUpdated={vi.fn()}
      />
    )
    expect(screen.getByText("Production — 1000 requests per minute", { exact: true })).toBeInTheDocument()
    expect(patchMock()).not.toHaveBeenCalled()
  })

  it("renders a native select with native options so registry drag exclusion applies", () => {
    const { container } = render(
      <TavilyRateTierSelect provider={provider()} canEdit onUpdated={vi.fn()} />
    )
    const select = container.querySelector("select")
    expect(select).not.toBeNull()
    expect(select!.getAttribute("aria-label")).toBe("Tavily rate tier (key environment)")
    for (const option of Array.from(select!.querySelectorAll("option"))) {
      expect(option.tagName).toBe("OPTION")
    }
  })
})

describe("TavilyRateTierSelect compact (FIX)", () => {
  function compactSelect(): HTMLSelectElement {
    return screen.getByRole("combobox", {
      name: "Tavily rate tier (key environment)",
      exact: true,
    }) as HTMLSelectElement
  }

  it("shows compact Development and Production options with no numeric rate text", () => {
    const { container } = render(
      <TavilyRateTierSelect provider={provider()} canEdit compact onUpdated={vi.fn()} />
    )
    const select = compactSelect()
    expect(select.tagName).toBe("SELECT")
    const options = Array.from(select.querySelectorAll("option"))
    expect(options.map((o) => o.getAttribute("value"))).toEqual(["dev", "prod"])
    expect(options.map((o) => o.textContent)).toEqual(["Development", "Production"])
    expect(container.textContent).not.toContain("100")
    expect(screen.getByText("Rate tier", { exact: true })).toBeInTheDocument()
  })

  it("shows compact keyless text with no select and zero PATCHes", () => {
    render(
      <TavilyRateTierSelect
        provider={provider({ keyVaultStatus: "keyless_public", hasKey: false })}
        canEdit
        compact
        onUpdated={vi.fn()}
      />
    )
    expect(screen.getByText("Keyless access", { exact: true })).toBeInTheDocument()
    expect(
      screen.queryByRole("combobox", { name: "Tavily rate tier (key environment)", exact: true })
    ).not.toBeInTheDocument()
    expect(document.body.textContent).not.toContain("100")
    expect(patchMock()).not.toHaveBeenCalled()
  })

  it("shows compact read-only text for reader roles with zero PATCHes", () => {
    render(
      <TavilyRateTierSelect provider={provider()} canEdit={false} compact onUpdated={vi.fn()} />
    )
    expect(screen.getByText("Development", { exact: true })).toBeInTheDocument()
    expect(
      screen.queryByRole("combobox", { name: "Tavily rate tier (key environment)", exact: true })
    ).not.toBeInTheDocument()
    expect(patchMock()).not.toHaveBeenCalled()
  })

  it("keeps compact Unknown locked when the status supplies no value", () => {
    render(
      <TavilyRateTierSelect
        provider={provider({ tavilyKeyEnvironment: null })}
        canEdit
        compact
        onUpdated={vi.fn()}
      />
    )
    expect(compactSelect()).toHaveValue("unknown")
    expect(compactSelect()).toBeDisabled()
    expect(patchMock()).not.toHaveBeenCalled()
  })
})

describe("TavilyRateTierSelect confirmation ordering and obsolete responses (FIX)", () => {
  function tierSelect(): HTMLSelectElement {
    return screen.getByRole("combobox", {
      name: "Tavily rate tier (key environment)",
      exact: true,
    }) as HTMLSelectElement
  }

  it("calls onConfirmed with the valid readback before onUpdated", async () => {
    const user = userEvent.setup()
    const order: string[] = []
    patchMock().mockResolvedValue({ tavily_key_environment: "prod" } as never)
    const onConfirmed = vi.fn((environment: string) => {
      order.push("confirmed:" + environment)
    })
    const onUpdated = vi.fn(async () => {
      order.push("updated")
    })
    render(
      <TavilyRateTierSelect
        provider={provider()}
        canEdit
        onConfirmed={onConfirmed}
        onUpdated={onUpdated}
      />
    )

    await user.selectOptions(tierSelect(), "prod")

    await waitFor(() => {
      expect(onConfirmed).toHaveBeenCalledTimes(1)
    })
    await waitFor(() => {
      expect(onUpdated).toHaveBeenCalledTimes(1)
    })
    expect(onConfirmed).toHaveBeenCalledWith("prod")
    expect(order).toEqual(["confirmed:prod", "updated"])
  })

  it("confirms a prod-to-dev change with one PATCH and the dev readback", async () => {
    const user = userEvent.setup()
    patchMock().mockResolvedValue({ tavily_key_environment: "dev" } as never)
    const onConfirmed = vi.fn()
    const onUpdated = vi.fn().mockResolvedValue(undefined)
    render(
      <TavilyRateTierSelect
        provider={provider({ tavilyKeyEnvironment: "prod" })}
        canEdit
        onConfirmed={onConfirmed}
        onUpdated={onUpdated}
      />
    )

    await user.selectOptions(tierSelect(), "dev")

    await waitFor(() => {
      expect(patchMock()).toHaveBeenCalledTimes(1)
    })
    expect(patchMock()).toHaveBeenCalledWith("tavily", { tavily_key_environment: "dev" })
    await waitFor(() => {
      expect(tierSelect()).toHaveValue("dev")
    })
    expect(onConfirmed).toHaveBeenCalledWith("dev")
    expect(onUpdated).toHaveBeenCalledTimes(1)
  })

  it("sends zero additional PATCHes when the selection matches the confirmed value", async () => {
    const user = userEvent.setup()
    patchMock().mockResolvedValue({ tavily_key_environment: "prod" } as never)
    const onUpdated = vi.fn().mockResolvedValue(undefined)
    render(<TavilyRateTierSelect provider={provider()} canEdit onUpdated={onUpdated} />)

    await user.selectOptions(tierSelect(), "prod")
    await waitFor(() => {
      expect(tierSelect()).toHaveValue("prod")
    })
    await user.selectOptions(tierSelect(), "prod")
    expect(patchMock()).toHaveBeenCalledTimes(1)
  })

  it("ignores the PATCH response after credential replacement", async () => {
    const user = userEvent.setup()
    let resolvePatch!: (value: unknown) => void
    patchMock().mockImplementation(
      () => new Promise((resolve) => { resolvePatch = resolve as (value: unknown) => void })
    )
    const onConfirmed = vi.fn()
    const onUpdated = vi.fn().mockResolvedValue(undefined)
    const { rerender } = render(
      <TavilyRateTierSelect
        provider={provider()}
        canEdit
        onConfirmed={onConfirmed}
        onUpdated={onUpdated}
      />
    )

    await user.selectOptions(tierSelect(), "prod")
    rerender(
      <TavilyRateTierSelect
        provider={provider({ keyVaultStatus: "missing", hasKey: false })}
        canEdit
        onConfirmed={onConfirmed}
        onUpdated={onUpdated}
      />
    )
    resolvePatch({ tavily_key_environment: "prod" })
    await new Promise((resolve) => setTimeout(resolve, 20))

    expect(onConfirmed).not.toHaveBeenCalled()
    expect(onUpdated).not.toHaveBeenCalled()
    expect(patchMock()).toHaveBeenCalledTimes(1)
  })

  it("keeps a valid stored value selectable when vendor tier metadata is absent", () => {
    // The vendor usage payload carries no key-environment field. The control
    // reads the application status value only, so a valid stored value stays
    // enabled while an absent application readback locks to Unknown.
    render(
      <TavilyRateTierSelect provider={provider({ tavilyKeyEnvironment: "dev" })} canEdit onUpdated={vi.fn()} />
    )
    expect(tierSelect()).toHaveValue("dev")
    expect(tierSelect()).not.toBeDisabled()
    expect(patchMock()).not.toHaveBeenCalled()
  })

  it("writes zero PATCHes for reader and keyless presentation", async () => {
    const user = userEvent.setup()
    const { unmount } = render(
      <TavilyRateTierSelect provider={provider()} canEdit={false} onUpdated={vi.fn()} />
    )
    await user.click(screen.getByText("Development — 100 requests per minute", { exact: true }))
    unmount()
    render(
      <TavilyRateTierSelect
        provider={provider({ keyVaultStatus: "keyless_public", hasKey: false })}
        canEdit
        onUpdated={vi.fn()}
      />
    )
    await user.click(screen.getByText("Keyless — numeric rate unknown", { exact: true }))
    expect(patchMock()).not.toHaveBeenCalled()
  })
})
