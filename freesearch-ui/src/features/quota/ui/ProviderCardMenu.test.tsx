import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ProviderCardMenu } from "./ProviderCardMenu"

/** Card `…` menu: every dialog of the card in sentence case, in one order. */

async function openMenu(manualEligible = true, onOpenModal = vi.fn()) {
  const user = userEvent.setup()
  render(<ProviderCardMenu providerName="Brave" manualEligible={manualEligible} onOpenModal={onOpenModal} />)
  await user.click(screen.getByRole("button", { name: "Actions for Brave" }))
  return { user, onOpenModal }
}

describe("ProviderCardMenu", () => {
  it("lists Set balance, Budget limit, and Balance history in order", async () => {
    await openMenu()
    expect(await screen.findByRole("button", { name: "Set balance" })).not.toBeNull()
    const labels = screen
      .getAllByRole("button")
      .map((button) => button.textContent)
      .filter((label) => label !== "")
    expect(labels).toEqual(["Set balance", "Budget limit", "Balance history"])
  })

  it("leaves Set balance out when the provider is not eligible", async () => {
    await openMenu(false)
    expect(await screen.findByRole("button", { name: "Budget limit" })).not.toBeNull()
    expect(screen.queryByRole("button", { name: "Set balance" })).toBeNull()
    expect(screen.getByRole("button", { name: "Balance history" })).not.toBeNull()
  })

  it("opens the matching dialog for each item", async () => {
    const { user, onOpenModal } = await openMenu()
    await user.click(await screen.findByRole("button", { name: "Set balance" }))
    expect(onOpenModal).toHaveBeenLastCalledWith("manual")
    await user.click(screen.getByRole("button", { name: "Actions for Brave" }))
    await user.click(await screen.findByRole("button", { name: "Budget limit" }))
    expect(onOpenModal).toHaveBeenLastCalledWith("grant")
    await user.click(screen.getByRole("button", { name: "Actions for Brave" }))
    await user.click(await screen.findByRole("button", { name: "Balance history" }))
    expect(onOpenModal).toHaveBeenLastCalledWith("history")
  })

  it("hides a budget for a free rail", async () => {
    render(<ProviderCardMenu providerName="Keenable" manualEligible={false} budgetAllowed={false} onOpenModal={vi.fn()} />)
    await userEvent.click(screen.getByRole("button", { name: "Actions for Keenable" }))
    expect(await screen.findByRole("button", { name: "Balance history" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Budget limit" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Set balance" })).toBeNull()
  })
})
