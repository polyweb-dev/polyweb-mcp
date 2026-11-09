import { render, screen, within } from "@testing-library/react"
import { expect, it } from "vitest"
import { Modal } from "./Modal"
import { ProviderDialogTitle } from "./ProviderDialogTitle"

it("names the dialog action and provider with one decorative logo", () => {
  render(<Modal isOpen onClose={() => {}}
    title={<ProviderDialogTitle providerId="brave" providerName="Brave Search" action="Balance history" />}>
    No balance changes
  </Modal>)
  const dialog = screen.getByRole("dialog", { name: "Balance history for Brave Search" })
  const heading = within(dialog).getByRole("heading", { name: "Balance history for Brave Search" })
  expect(within(heading).getByTestId("provider-logo-brave")).toHaveAttribute("aria-hidden", "true")
})
