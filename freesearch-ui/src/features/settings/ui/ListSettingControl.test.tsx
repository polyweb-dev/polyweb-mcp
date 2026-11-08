import { describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ListSettingControl } from "./ListSettingControl"

/**
 * The preferred-providers picker. The routing section is hidden on the page
 * until the backend applies it, so the control is exercised directly here.
 */
describe("ListSettingControl", () => {
  it("adds providers by name in order and reports their wire ids", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    const { rerender } = render(
      <ListSettingControl id="pref" label="Preferred providers" value={[]} disabled={false} onChange={onChange} />
    )
    await user.click(screen.getByRole("combobox", { name: "Add preferred provider" }))
    await user.click(screen.getByRole("option", { name: "You.com" }))
    expect(onChange).toHaveBeenLastCalledWith(["you"])

    rerender(<ListSettingControl id="pref" label="Preferred providers" value={["you"]} disabled={false} onChange={onChange} />)
    const list = screen.getByRole("list", { name: "Preferred providers" })
    expect(within(list).getByText("You.com")).toBeInTheDocument()
    await user.click(screen.getByRole("combobox", { name: "Add preferred provider" }))
    expect(screen.queryByRole("option", { name: "You.com" })).toBeNull()
    await user.click(screen.getByRole("option", { name: "Exa" }))
    expect(onChange).toHaveBeenLastCalledWith(["you", "exa"])
  })

  it("removes a chosen provider", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<ListSettingControl id="pref" label="Preferred providers" value={["tavily", "exa"]} disabled={false} onChange={onChange} />)
    await user.click(screen.getByRole("button", { name: "Remove Tavily" }))
    expect(onChange).toHaveBeenLastCalledWith(["exa"])
  })
})
