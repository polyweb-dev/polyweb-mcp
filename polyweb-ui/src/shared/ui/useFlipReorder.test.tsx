import { render } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { useFlipReorder } from "./useFlipReorder"

function Table({ order }: { order: string[] }) {
  const ref = useFlipReorder(order.join("|"))
  return <table><tbody ref={ref}>{order.map((id) => <tr key={id} data-provider={id}><td>{id}</td></tr>)}</tbody></table>
}

afterEach(() => vi.restoreAllMocks())

describe("useFlipReorder", () => {
  it("animates the final list together without animating individual rows", () => {
    const cancel = vi.fn()
    const animate = vi.fn(() => ({ cancel }))
    const view = render(<Table order={["a", "b"]} />)
    const body = view.container.querySelector("tbody")
    if (!body) throw new Error("Missing table body")
    body.animate = animate as unknown as typeof body.animate
    view.rerender(<Table order={["b", "a"]} />)
    expect(Array.from(body.rows, (row) => row.textContent)).toEqual(["b", "a"])
    expect(animate).toHaveBeenCalledWith([{ transform: "translateY(4px)" }, { transform: "translateY(0)" }], expect.objectContaining({ duration: 150 }))
    view.unmount()
    expect(cancel).toHaveBeenCalledOnce()
  })

  it("does not animate when reduced motion is requested", () => {
    vi.stubGlobal("matchMedia", () => ({ matches: true }))
    const view = render(<Table order={["a", "b"]} />)
    const body = view.container.querySelector("tbody")
    if (!body) throw new Error("Missing table body")
    body.animate = vi.fn()
    view.rerender(<Table order={["b", "a"]} />)
    expect(body.animate).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })
})
