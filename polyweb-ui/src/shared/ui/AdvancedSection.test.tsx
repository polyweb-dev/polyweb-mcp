import { expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { AdvancedSection } from "./AdvancedSection"

it("discloses advanced fields on request", async () => {
  render(<AdvancedSection label="Advanced"><span>Key limit</span></AdvancedSection>)
  expect(screen.queryByText("Key limit")).toBeNull()
  await userEvent.click(screen.getByRole("button", { name: "Advanced" }))
  expect(screen.getByText("Key limit")).toBeInTheDocument()
})
