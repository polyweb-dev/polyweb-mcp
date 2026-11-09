import { render, screen, within } from "@testing-library/react"
import { expect, it } from "vitest"
import { Modal } from "./Modal"
import { ProviderDialogTitle } from "./ProviderDialogTitle"

it("names the dialog action and provider with one decorative logo", () => {
  render(<Modal isOpen onClose={() => {}}
    title={<ProviderDialogTitle providerId="brave" title="Brave Search balance history" />}>
    No balance changes
  </Modal>)
  const dialog = screen.getByRole("dialog", { name: "Brave Search balance history" })
  const heading = within(dialog).getByRole("heading", { name: "Brave Search balance history" })
  expect(within(heading).getByTestId("provider-logo-brave")).toHaveAttribute("aria-hidden", "true")
})
