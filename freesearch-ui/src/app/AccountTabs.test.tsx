import { expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { AccountTabs } from "./AccountTabs"

it.each(["profile", "keys"] as const)("shows the %s page without duplicate account tabs", (page) => {
  render(<AccountTabs page={page}>Account content</AccountTabs>)
  expect(screen.getByText("Account content")).toBeInTheDocument()
  expect(screen.queryByRole("tablist")).not.toBeInTheDocument()
})
