import { describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ApiKeyRevealDialog } from "./ApiKeyRevealDialog"

/** Opaque stand-in for a one-time key; it is not a real credential. */
const ONE_TIME_VALUE = "fs_live_test-only-opaque-value"

describe("ApiKeyRevealDialog", () => {
  it("renders nothing without a key", () => {
    render(<ApiKeyRevealDialog rawKey={null} onDone={() => {}} />)
    expect(screen.queryByRole("dialog")).toBeNull()
  })

  it("shows the key once in a read-only field with the warning and actions", () => {
    render(<ApiKeyRevealDialog rawKey={ONE_TIME_VALUE} onDone={() => {}} />)
    const dialog = screen.getByRole("dialog", { name: "Copy your new API key" })
    expect(within(dialog).getByText("This key is shown only once.")).toBeInTheDocument()
    const field = within(dialog).getByLabelText("API key")
    expect(field).toHaveValue(ONE_TIME_VALUE)
    expect(field).toHaveAttribute("readonly")
    expect(within(dialog).getByRole("button", { name: "Copy key" })).toBeInTheDocument()
    expect(within(dialog).getByRole("button", { name: "Done" })).toBeInTheDocument()
  })

  it("copies the key and confirms without echoing it", async () => {
    const user = userEvent.setup()
    const writeText = vi.fn(async () => {})
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true })
    render(<ApiKeyRevealDialog rawKey={ONE_TIME_VALUE} onDone={() => {}} />)

    await user.click(screen.getByRole("button", { name: "Copy key" }))
    expect(writeText).toHaveBeenCalledWith(ONE_TIME_VALUE)
    const status = await screen.findByText("Copied to the clipboard.")
    expect(status.textContent).not.toContain(ONE_TIME_VALUE)
  })

  it.each([
    ["Done", async (user: ReturnType<typeof userEvent.setup>) => user.click(screen.getByRole("button", { name: "Done" }))],
    ["Escape", async (user: ReturnType<typeof userEvent.setup>) => user.keyboard("{Escape}")],
    ["the close control", async (user: ReturnType<typeof userEvent.setup>) => user.click(screen.getByRole("button", { name: "Close" }))],
  ])("clears the key through onDone on %s", async (_how, act) => {
    const user = userEvent.setup()
    const onDone = vi.fn()
    render(<ApiKeyRevealDialog rawKey={ONE_TIME_VALUE} onDone={onDone} />)
    await act(user)
    await waitFor(() => expect(onDone).toHaveBeenCalled())
  })
})
