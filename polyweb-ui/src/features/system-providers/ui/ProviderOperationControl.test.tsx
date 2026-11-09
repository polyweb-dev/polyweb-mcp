import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { OperationControl } from "./ProviderOperationControl"

describe("ProviderOperationControl", () => {
  it("shows an unsupported tool as an unavailable dash with a Not supported tooltip", async () => {
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

    expect(screen.queryByRole("switch")).toBeNull()
    expect(screen.getByText("Brave Search does not support fetch")).toBeInTheDocument()
    const dash = screen.getByText("—")
    await user.hover(dash)
    expect(await screen.findByText("Not supported")).toBeInTheDocument()
  })

  it("keeps the unsupported dash while global access stays OFF and for read-only roles", () => {
    const { rerender } = render(
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

    expect(screen.queryByRole("switch")).toBeNull()
    expect(screen.getByText("—")).toBeInTheDocument()

    rerender(
      <OperationControl
        label="Fetch"
        providerName="Brave Search"
        supported={false}
        enabled={false}
        globallyDisabled={false}
        canEdit={false}
        pending={false}
        onToggle={() => {}}
      />,
    )
    expect(screen.getByText("—")).toBeInTheDocument()
    expect(screen.queryByText("Off")).toBeNull()
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
