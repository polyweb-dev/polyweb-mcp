import { describe, it, expect, afterEach, vi } from "vitest"
import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { AccountPage } from "./AccountPage"
import { renderAuthenticated } from "@/test/renderAuthenticated"
import {
  ADMIN_ACCOUNT_ID,
  TEST_ACCESS_TOKEN,
  adminAccountFixture,
  agentAccountFixture,
  developerAccountFixture,
} from "@/test/authFixtures"

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("AccountPage", () => {
  it("shows the email, id, role, active, and verification values", () => {
    renderAuthenticated(<AccountPage />, { account: adminAccountFixture() })

    expect(screen.getByText("admin@example.com")).toBeInTheDocument()
    expect(screen.getByText(ADMIN_ACCOUNT_ID)).toBeInTheDocument()
    expect(screen.getByText("admin")).toBeInTheDocument()
    expect(screen.getAllByText("Active")).toHaveLength(2)
    expect(screen.getByText("Verified")).toBeInTheDocument()
  })

  it("calls logout when the Sign out button is clicked", async () => {
    const user = userEvent.setup()
    const { logout } = renderAuthenticated(<AccountPage />, { account: adminAccountFixture() })

    await user.click(screen.getByRole("button", { name: "Sign out" }))

    expect(logout).toHaveBeenCalledTimes(1)
  })

  it("shows the Admin creation link to an admin account", () => {
    renderAuthenticated(<AccountPage />, { account: adminAccountFixture() })

    const adminLink = screen.getByRole("link", { name: "Create accounts" })
    expect(adminLink).toHaveAttribute("href", "/admin/users")
  })

  it("shows no Admin link to a developer account", () => {
    renderAuthenticated(<AccountPage />, { account: developerAccountFixture() })

    expect(screen.getByText("developer@example.com")).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "Create accounts" })).toBeNull()
  })

  it("shows no Admin link to an agent account", () => {
    renderAuthenticated(<AccountPage />, { account: agentAccountFixture() })

    expect(screen.getByText("agent@example.com")).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "Create accounts" })).toBeNull()
  })

  it("renders nothing when the account is null", () => {
    const { container } = renderAuthenticated(<AccountPage />, { account: null })

    expect(container.firstChild).toBeNull()
    expect(container.textContent).toBe("")
  })

  it("holds no access or refresh credential text", () => {
    renderAuthenticated(<AccountPage />, { account: adminAccountFixture() })

    expect(screen.queryByText(TEST_ACCESS_TOKEN)).toBeNull()
    const bodyText = document.body.textContent ?? ""
    expect(bodyText).not.toContain(TEST_ACCESS_TOKEN)
    expect(bodyText).not.toMatch(/refresh_token/i)
  })
})
