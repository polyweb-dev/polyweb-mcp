import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Brand } from "./SidebarBrand"

describe("SidebarBrand expanded output", () => {
  it("renders the static brand with logo text and no button", () => {
    render(<Brand />)

    expect(screen.getByText("Polyweb", { exact: true })).toBeInTheDocument()
    expect(screen.getByRole("presentation", { hidden: true })).toBeInTheDocument()
    expect(screen.queryByRole("button")).not.toBeInTheDocument()
  })

  it("renders the centered static mark without text when collapsed without a callback", () => {
    render(<Brand collapsed />)

    expect(screen.getByRole("presentation", { hidden: true })).toBeInTheDocument()
    expect(screen.queryByText("Polyweb")).not.toBeInTheDocument()
    expect(screen.queryByRole("button")).not.toBeInTheDocument()
  })
})

describe("SidebarBrand collapsed expansion control", () => {
  it("exposes exactly one expansion button with the logo and the icon", () => {
    render(<Brand collapsed onExpand={() => {}} />)

    const button = screen.getByRole("button", { name: "Expand sidebar", exact: true })
    expect(button).toBeInTheDocument()
    expect(screen.getAllByRole("button")).toHaveLength(1)
    expect(button.querySelector("img")).not.toBeNull()
    expect(button.querySelector("svg")).not.toBeNull()
  })

  it("calls the expansion callback exactly once per press", async () => {
    const user = userEvent.setup()
    const onExpand = vi.fn()
    render(<Brand collapsed onExpand={onExpand} />)

    await user.click(screen.getByRole("button", { name: "Expand sidebar", exact: true }))

    expect(onExpand).toHaveBeenCalledTimes(1)
  })

  it("carries the collapsed accessible attributes", () => {
    render(<Brand collapsed onExpand={() => {}} />)

    const button = screen.getByRole("button", { name: "Expand sidebar", exact: true })
    expect(button).toHaveAttribute("aria-expanded", "false")
    expect(button).toHaveAttribute("aria-controls", "primary-sidebar")
    expect(button).toHaveAttribute("title", "Expand sidebar")
  })

  it("activates through keyboard Enter", async () => {
    const user = userEvent.setup()
    const onExpand = vi.fn()
    render(<Brand collapsed onExpand={onExpand} />)

    screen.getByRole("button", { name: "Expand sidebar", exact: true }).focus()
    await user.keyboard("{Enter}")

    expect(onExpand).toHaveBeenCalledTimes(1)
  })

  it("activates through keyboard Space", async () => {
    const user = userEvent.setup()
    const onExpand = vi.fn()
    render(<Brand collapsed onExpand={onExpand} />)

    screen.getByRole("button", { name: "Expand sidebar", exact: true }).focus()
    await user.keyboard(" ")

    expect(onExpand).toHaveBeenCalledTimes(1)
  })
})
