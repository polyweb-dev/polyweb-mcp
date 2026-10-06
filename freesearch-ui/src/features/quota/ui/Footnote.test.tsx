import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { Footnote } from "./Footnote"

/**
 * Polish locking suite: one quiet footnote paragraph with optional layout.
 */

describe("Footnote", () => {
  it("renders children in one paragraph", () => {
    render(<Footnote>Quiet note</Footnote>)
    const note = screen.getByText("Quiet note")
    expect(note.tagName).toBe("P")
  })

  it("uses the three quiet classes", () => {
    render(<Footnote>Quiet note</Footnote>)
    const note = screen.getByText("Quiet note")
    expect(note.classList.contains("text-[11px]")).toBe(true)
    expect(note.classList.contains("leading-relaxed")).toBe(true)
    expect(note.classList.contains("text-[var(--muted)]")).toBe(true)
  })

  it("appends an optional class name", () => {
    render(<Footnote className="mt-4">Quiet note</Footnote>)
    const note = screen.getByText("Quiet note")
    expect(note.className).toContain("mt-4")
    expect(note.classList.contains("text-[11px]")).toBe(true)
  })
})
