import { describe, it, expect, afterEach, vi } from "vitest"
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { AdminUsersPage } from "./AdminUsersPage"
import { renderAuthenticated } from "@/test/renderAuthenticated"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import {
  adminAccountFixture,
  agentAccountFixture,
  developerAccountFixture,
} from "@/test/authFixtures"
import {
  SETTINGS_READER_PERMISSIONS,
  SYSTEM_ADMIN_PERMISSIONS,
} from "@/test/accessFixtures"

function stubProvision() {
  return installFetchStub((req) => {
    if (req.method === "POST" && req.url === "/api/v1/users") {
      const body = req.body as { email: string }
      return ok({
        id: "55555555-5555-4555-8555-555555555555",
        email: body.email,
        auth_provider: "local",
        auth_provider_id: null,
        username: null,
        first_name: null,
        last_name: null,
        is_active: true,
        is_verified: false,
      })
    }
    return err(404, { detail: "unhandled test route" })
  })
}

const ADMIN = { account: adminAccountFixture(), systemPermissions: SYSTEM_ADMIN_PERMISSIONS }

describe("AdminUsersPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("shows the creation form without a role control under system.settings.write", () => {
    stubProvision()
    renderAuthenticated(<AdminUsersPage />, ADMIN)

    expect(screen.getByRole("heading", { name: "Accounts" })).toBeInTheDocument()
    expect(screen.getByLabelText("Email")).toBeInTheDocument()
    expect(screen.getByLabelText("Password")).toBeInTheDocument()
    expect(screen.getByLabelText("Confirm password")).toBeInTheDocument()
    expect(screen.queryByLabelText("Account role")).toBeNull()
    expect(screen.queryByRole("combobox")).toBeNull()
    expect(screen.getByRole("button", { name: "Create account" })).toBeInTheDocument()
    expect(screen.queryByLabelText("Account UUID")).toBeNull()
    expect(screen.queryByLabelText("New role")).toBeNull()
  })

  it("offers no role or account-type option", () => {
    stubProvision()
    renderAuthenticated(<AdminUsersPage />, ADMIN)

    expect(screen.queryByRole("option")).toBeNull()
    expect(screen.queryByLabelText(/account type/i)).toBeNull()
  })

  it("states that project association comes later", () => {
    stubProvision()
    renderAuthenticated(<AdminUsersPage />, ADMIN)

    expect(screen.getByText(/later project association/)).toBeInTheDocument()
    expect(screen.getByText(/no authority over an existing account/)).toBeInTheDocument()
  })

  it("creates the account from email and password only and shows the safe receipt", async () => {
    const stub = stubProvision()
    renderAuthenticated(<AdminUsersPage />, ADMIN)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText("Email"), "newdev@example.com")
    await user.type(screen.getByLabelText("Password"), "correct-horse-battery-99")
    await user.type(screen.getByLabelText("Confirm password"), "correct-horse-battery-99")
    await user.click(screen.getByRole("button", { name: "Create account" }))

    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(
        "Created the account newdev@example.com.",
      )
    })
    expect(screen.getByText("newdev@example.com")).toBeInTheDocument()
    expect(screen.queryByText("Role")).toBeNull()
    const posts = stub.requestsTo("/api/v1/users")
    expect(posts).toHaveLength(1)
    expect(posts[0]?.body).toEqual({
      email: "newdev@example.com",
      password: "correct-horse-battery-99",
    })
  })

  it("rejects a short password with the shared rule before any request", async () => {
    const stub = stubProvision()
    renderAuthenticated(<AdminUsersPage />, ADMIN)
    const user = userEvent.setup()

    expect(screen.getByText("Use 12 to 128 characters.")).toBeInTheDocument()
    await user.type(screen.getByLabelText("Email"), "newdev@example.com")
    await user.type(screen.getByLabelText("Password"), "short-pw")
    await user.type(screen.getByLabelText("Confirm password"), "short-pw")
    await user.click(screen.getByRole("button", { name: "Create account" }))

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Use at least 12 characters for the password.",
    )
    expect(stub.requests).toHaveLength(0)
  })

  it("shows an alert when the passwords do not match", async () => {
    const stub = stubProvision()
    renderAuthenticated(<AdminUsersPage />, ADMIN)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText("Email"), "newdev@example.com")
    await user.type(screen.getByLabelText("Password"), "correct-horse-battery-99")
    await user.type(screen.getByLabelText("Confirm password"), "different-horse-battery-11")
    await user.click(screen.getByRole("button", { name: "Create account" }))

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The two passwords do not match.",
    )
    expect(stub.requests).toHaveLength(0)
  })

  it("shows the friendly rule without raw JSON for a coded password failure", async () => {
    installFetchStub((req) => {
      if (req.method === "POST" && req.url === "/api/v1/users") {
        return err(400, {
          detail: { code: "REGISTER_INVALID_PASSWORD", reason: "weak password" },
        })
      }
      return err(404, { detail: "unhandled test route" })
    })
    renderAuthenticated(<AdminUsersPage />, ADMIN)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText("Email"), "newdev@example.com")
    await user.type(screen.getByLabelText("Password"), "correct-horse-battery-99")
    await user.type(screen.getByLabelText("Confirm password"), "correct-horse-battery-99")
    await user.click(screen.getByRole("button", { name: "Create account" }))

    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent(
      "Use 12 to 128 characters with an upper-case letter, a lower-case letter, a digit, and a symbol."
    )
    expect(alert.textContent ?? "").not.toContain("REGISTER_INVALID_PASSWORD")
    expect(alert.textContent ?? "").not.toContain("{")
  })

  it("restricts the screen with system.settings.read only", () => {
    renderAuthenticated(<AdminUsersPage />, {
      account: developerAccountFixture(),
      systemPermissions: SETTINGS_READER_PERMISSIONS,
    })

    expect(
      screen.getByRole("heading", { name: "Accounts" }),
    ).toBeInTheDocument()
    expect(screen.getByRole("status")).toHaveTextContent(
      "available to system administrators only",
    )
    expect(screen.queryByRole("textbox")).toBeNull()
    expect(screen.queryByRole("combobox")).toBeNull()
    expect(
      screen.queryByRole("button", { name: "Create account" }),
    ).toBeNull()
  })

  it("restricts the screen without system permissions", () => {
    renderAuthenticated(<AdminUsersPage />, { account: agentAccountFixture(), systemPermissions: [] })

    expect(
      screen.getByRole("heading", { name: "Accounts" }),
    ).toBeInTheDocument()
    expect(screen.getByRole("status")).toHaveTextContent(
      "available to system administrators only",
    )
    expect(screen.queryByRole("textbox")).toBeNull()
    expect(screen.queryByRole("combobox")).toBeNull()
    expect(
      screen.queryByRole("button", { name: "Create account" }),
    ).toBeNull()
  })

  it("restricts the screen while no system access is known", () => {
    renderAuthenticated(<AdminUsersPage />, { account: adminAccountFixture() })
    expect(screen.getByRole("status")).toHaveTextContent("available to system administrators only")
    expect(screen.queryByRole("button", { name: "Create account" })).toBeNull()
  })

  it("restricts the screen for an anonymous visitor", () => {
    renderAuthenticated(<AdminUsersPage />, { account: null, systemPermissions: SYSTEM_ADMIN_PERMISSIONS })

    expect(
      screen.getByRole("heading", { name: "Accounts" }),
    ).toBeInTheDocument()
    expect(screen.getByRole("status")).toHaveTextContent(
      "available to system administrators only",
    )
    expect(screen.queryByRole("textbox")).toBeNull()
    expect(screen.queryByRole("combobox")).toBeNull()
    expect(
      screen.queryByRole("button", { name: "Create account" }),
    ).toBeNull()
  })
})
