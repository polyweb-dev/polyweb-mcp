import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import { decodeProviderTypeView } from "@/domains/providers/api/credentialsWire"
import { ProvidersWithoutCapacity } from "./ProvidersWithoutCapacity"

const providers = ["you", "exa", "brave"].map((provider_type) => {
  const provider = decodeProviderTypeView({ provider_type })
  if (!provider) throw new Error("Missing provider fixture")
  return provider
})

describe("ProvidersWithoutCapacity", () => {
  it("sorts the compact list by display name and adds capacity from its row", async () => {
    const add = vi.fn()
    render(<ProvidersWithoutCapacity providers={providers} isOwner onAdd={add} />)
    const list = screen.getByRole("list", { name: "Without capacity" })
    expect(within(list).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Brave SearchAdd capacity", "ExaAdd capacity", "You.comAdd capacity",
    ])
    await userEvent.click(screen.getByRole("button", { name: "Add capacity for Brave Search" }))
    expect(add).toHaveBeenCalledExactlyOnceWith("brave")
    expect(providers.map((provider) => provider.providerType)).toEqual(["you", "exa", "brave"])
  })

  it("shows no actions for a viewer and omits an empty section", () => {
    const { rerender } = render(<ProvidersWithoutCapacity providers={providers} isOwner={false} onAdd={vi.fn()} />)
    expect(screen.queryByRole("button")).toBeNull()
    expect(screen.getAllByText("The provider owner must add capacity")).toHaveLength(3)
    rerender(<ProvidersWithoutCapacity providers={[]} isOwner onAdd={vi.fn()} />)
    expect(screen.queryByRole("list")).toBeNull()
  })
})
