import { afterEach, describe, expect, it, vi } from "vitest"
import { render } from "@testing-library/react"
import { useDialogFocusTrap } from "./useDialogFocusTrap"

/** A dialog whose body never renders a control, so focus entry keeps retrying. */
function EmptyDialog() {
  const ref = useDialogFocusTrap()
  return <div ref={ref} role="dialog" aria-label="Empty" />
}

describe("useDialogFocusTrap", () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it("cancels the pending focus retry on unmount", () => {
    vi.useFakeTimers()
    const view = render(<EmptyDialog />)
    vi.advanceTimersByTime(40)
    expect(vi.getTimerCount()).toBe(1)

    view.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it("focuses the first control once it exists", () => {
    vi.useFakeTimers()
    // jsdom lays nothing out; give every element one box so it counts as reachable.
    vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([
      new DOMRect(0, 0, 10, 10),
    ] as unknown as DOMRectList)
    function Dialog() {
      const ref = useDialogFocusTrap()
      return (
        <div ref={ref} role="dialog" aria-label="Form">
          <button type="button">Confirm</button>
        </div>
      )
    }
    const view = render(<Dialog />)
    expect(view.getByRole("button", { name: "Confirm" })).toHaveFocus()
  })
})
