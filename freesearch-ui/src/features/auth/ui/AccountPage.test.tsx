import { describe, it, expect, afterEach, vi } from "vitest"
import { screen } from "@testing-library/react"
import { AccountPage } from "./AccountPage"
import { renderAuthenticated } from "@/test/renderAuthenticated"
import {
  ADMIN_ACCOUNT_ID,
  TEST_ACCESS_TOKEN,
  adminAccountFixture,
  agentAccountFixture,
  developerAccountFixture,
} from "@/test/authFixtures"
import {
  SETTINGS_READER_PERMISSIONS,
  SYSTEM_ADMIN_PERMISSIONS,
} from "@/test/accessFixtures"

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("AccountPage", () => {
  it("shows one card of email and sign-in facts without id, status, verification or role", () => {
    renderAuthenticated(<AccountPage />, { account: adminAccountFixture() })

    expect(screen.getByText("admin@example.com")).toBeInTheDocument()
    expect(screen.queryByText(ADMIN_ACCOUNT_ID)).toBeNull()
    expect(screen.queryByText("Role")).toBeNull()
    expect(screen.queryByText("Admin")).toBeNull()
    expect(screen.queryByText("Status")).toBeNull()
    expect(screen.queryByText("Active")).toBeNull()
    expect(screen.queryByText("Email verification")).toBeNull()
    expect(screen.queryByText("Verified")).toBeNull()
    expect(screen.queryByText("Name")).toBeNull()
    expect(screen.getByText("Email and password")).toBeInTheDocument()
    expect(screen.getByText("Email").closest("dl")).toHaveClass("grid-cols-2")
    expect(screen.getAllByRole("heading")).toHaveLength(1)
  })

  it("omits verification when no supported action exists", () => {
    renderAuthenticated(<AccountPage />, { account: adminAccountFixture({ is_verified: false }) })
    expect(screen.queryByText("Email verification")).toBeNull()
    expect(screen.queryByText("Not verified")).toBeNull()
    expect(screen.getByText("admin@example.com")).toBeInTheDocument()
    expect(screen.queryByRole("button")).toBeNull()
  })

  it("shows the full name when the account has one, else the username", () => {
    const { unmount } = renderAuthenticated(<AccountPage />, {
      account: adminAccountFixture({ first_name: "Ada", last_name: "Lovelace", username: "ada" }),
    })
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument()
    unmount()

    renderAuthenticated(<AccountPage />, { account: adminAccountFixture({ username: "ada" }) })
    expect(screen.getByText("ada")).toBeInTheDocument()
  })

  it("shows no Sign out action on the account page", () => {
    renderAuthenticated(<AccountPage />, { account: adminAccountFixture() })

    expect(
      screen.queryByRole("button", { name: "Sign out" })
    ).not.toBeInTheDocument()
  })

  it("shows no account creation link even with system.settings.write", () => {
    renderAuthenticated(<AccountPage />, {
      account: adminAccountFixture(),
      systemPermissions: SYSTEM_ADMIN_PERMISSIONS,
    })

    expect(screen.queryByRole("link", { name: "Create accounts" })).toBeNull()
  })

  it("shows no account creation link with system.settings.read only", () => {
    renderAuthenticated(<AccountPage />, {
      account: developerAccountFixture(),
      systemPermissions: SETTINGS_READER_PERMISSIONS,
    })

    expect(screen.getByText("developer@example.com")).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "Create accounts" })).toBeNull()
  })

  it("shows no account creation link without system permissions or a projects surface", () => {
    renderAuthenticated(<AccountPage />, { account: agentAccountFixture(), systemPermissions: [] })
    expect(screen.getByText("agent@example.com")).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "Create accounts" })).toBeNull()
  })

  it("shows no security explainer copy", () => {
    renderAuthenticated(<AccountPage />, { account: adminAccountFixture() })
    expect(screen.queryByText(/never shows a credential/)).toBeNull()
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
