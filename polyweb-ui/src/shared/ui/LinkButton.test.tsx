import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { expect, it } from "vitest"
import { MemoryRouter, Route, Routes } from "react-router"
import { Button } from "./button"
import { LinkButton } from "./LinkButton"

it("uses the outline small button surface and follows a router destination", async () => {
  render(
    <MemoryRouter>
      <Button variant="outline" size="sm">Refresh</Button>
      <LinkButton to="/activity">See calls</LinkButton>
      <Routes>
        <Route path="/" element={<p>Usage</p>} />
        <Route path="/activity" element={<h1>Activity</h1>} />
      </Routes>
    </MemoryRouter>
  )
  const link = screen.getByRole("link", { name: "See calls" })
  expect(link).toHaveClass(...screen.getByRole("button", { name: "Refresh" }).classList)
  expect(link).toHaveAttribute("data-slot", "button")
  await userEvent.click(link)
  expect(screen.getByRole("heading", { name: "Activity" })).toBeInTheDocument()
})

it("keeps external navigation and its accessible name", () => {
  render(<MemoryRouter><LinkButton to="https://example.com" target="_blank" rel="noreferrer" aria-label="Open result">Open</LinkButton></MemoryRouter>)
  const link = screen.getByRole("link", { name: "Open result" })
  expect(link).toHaveAttribute("href", "https://example.com")
  expect(link).toHaveAttribute("target", "_blank")
  expect(link).toHaveAttribute("rel", "noreferrer")
})
