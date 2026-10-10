import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { OperationControl } from "./ProviderOperationControl"

describe("ProviderOperationControl", () => {
  it("shows an unsupported tool as OFF and unavailable with a support label", async () => {
    const user = userEvent.setup()
    render(
      <OperationControl
        label="Fetch"
        providerName="Brave Search"
        supported={false}
        enabled={false}
        globallyDisabled={false}
        canEdit
        pending={false}
        onToggle={() => {}}
      />,
    )

    const control = screen.getByRole("switch", {
      name: "Brave Search fetch routing (not supported)",
    })
    expect(control).toBeInTheDocument()
    expect(control).toHaveAttribute("aria-checked", "false")
    expect(control).toBeDisabled()
    await user.hover(control)
    expect(await screen.findByText("Brave Search does not support fetch")).toBeInTheDocument()
  })

  it("keeps the unsupported OFF state while global access stays OFF", () => {
    render(
      <OperationControl
        label="Fetch"
        providerName="Brave Search"
        supported={false}
        enabled={false}
        globallyDisabled
        canEdit
        pending={false}
        onToggle={() => {}}
      />,
    )

    const control = screen.getByRole("switch", {
      name: "Brave Search fetch routing (not supported)",
    })
    expect(control).toHaveAttribute("aria-checked", "false")
    expect(control).toBeDisabled()
  })

  it("disables every access control while its row request stays pending", async () => {
    const user = userEvent.setup()
    const onToggle = vi.fn()
    const { rerender } = render(
      <OperationControl
        label="Search"
        providerName="Tavily"
        supported
        enabled
        globallyDisabled={false}
        canEdit
        pending={false}
        onToggle={onToggle}
      />,
    )

    const active = screen.getByRole("switch", { name: "Tavily search routing" })
    expect(active).not.toBeDisabled()
    await user.click(active)
    expect(onToggle).toHaveBeenCalledTimes(1)

    onToggle.mockClear()
    rerender(
      <OperationControl
        label="Search"
        providerName="Tavily"
        supported
        enabled
        globallyDisabled={false}
        canEdit
        pending
        onToggle={onToggle}
      />,
    )
    const pendingControl = screen.getByRole("switch", { name: "Tavily search routing" })
    expect(pendingControl).toBeDisabled()
    await user.click(pendingControl)
    expect(onToggle).not.toHaveBeenCalled()
  })

  it("preserves the raw checked value under the global lock", () => {
    const { rerender } = render(
      <OperationControl
        label="Search"
        providerName="Tavily"
        supported
        enabled
        globallyDisabled
        canEdit
        pending={false}
        onToggle={() => {}}
      />,
    )

    const locked = screen.getByRole("switch", { name: "Tavily search routing" })
    expect(locked).toHaveAttribute("aria-checked", "true")
    expect(locked).toBeDisabled()

    rerender(
      <OperationControl
        label="Search"
        providerName="Tavily"
        supported
        enabled
        globallyDisabled={false}
        canEdit
        pending={false}
        onToggle={() => {}}
      />,
    )
    const unlocked = screen.getByRole("switch", { name: "Tavily search routing" })
    expect(unlocked).toHaveAttribute("aria-checked", "true")
    expect(unlocked).not.toBeDisabled()
  })

  it("keeps accessible provider-qualified labels for both tools", () => {
    const { unmount } = render(
      <OperationControl
        label="Search"
        providerName="Exa"
        supported
        enabled={false}
        globallyDisabled={false}
        canEdit
        pending={false}
        onToggle={() => {}}
      />,
    )
    expect(
      screen.getByRole("switch", { name: "Exa search routing" }),
    ).toHaveAttribute("aria-checked", "false")
    unmount()

    render(
      <OperationControl
        label="Fetch"
        providerName="Exa"
        supported
        enabled
        globallyDisabled={false}
        canEdit
        pending={false}
        onToggle={() => {}}
      />,
    )
    expect(
      screen.getByRole("switch", { name: "Exa fetch routing" }),
    ).toHaveAttribute("aria-checked", "true")
  })
})
