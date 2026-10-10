import { describe, it, expect, afterEach, vi } from "vitest"
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { AdminUsersPage } from "./AdminUsersPage"
import { renderAuthenticated } from "@/test/renderAuthenticated"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import type { UserRole } from "@/domains/auth"
import {
  adminAccountFixture,
  agentAccountFixture,
  developerAccountFixture,
} from "@/test/authFixtures"

function stubProvision() {
  return installFetchStub((req) => {
    if (req.method === "POST" && req.url === "/api/v1/users") {
      const body = req.body as { email: string; role: UserRole }
      return ok({
        id: "55555555-5555-4555-8555-555555555555",
        email: body.email,
        role: body.role,
        is_active: true,
        is_superuser: body.role === "admin",
        is_verified: false,
      })
    }
    return err(404, { detail: "unhandled test route" })
  })
}

describe("AdminUsersPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("shows the creation form with the role select for an admin", () => {
    stubProvision()
    renderAuthenticated(<AdminUsersPage />, { account: adminAccountFixture() })

    expect(screen.getByRole("heading", { name: "Account roles" })).toBeInTheDocument()
    expect(screen.getByLabelText("Email")).toBeInTheDocument()
    expect(screen.getByLabelText("Password")).toBeInTheDocument()
    expect(screen.getByLabelText("Confirm password")).toBeInTheDocument()
    expect(screen.getByLabelText("Account role")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Create account" })).toBeInTheDocument()
    expect(screen.queryByLabelText("Account UUID")).toBeNull()
    expect(screen.queryByLabelText("New role")).toBeNull()
  })

  it("offers all three roles starting on Agent", () => {
    stubProvision()
    renderAuthenticated(<AdminUsersPage />, { account: adminAccountFixture() })

    expect((screen.getByLabelText("Account role") as HTMLSelectElement).value).toBe("agent")
    const values = screen
      .getAllByRole("option")
      .map((option) => (option as HTMLOptionElement).value)
    expect(values).toEqual(["admin", "developer", "agent"])
  })

  it("states that project association comes later", () => {
    stubProvision()
    renderAuthenticated(<AdminUsersPage />, { account: adminAccountFixture() })

    expect(screen.getByText(/later project association/)).toBeInTheDocument()
    expect(screen.getByText(/no authority over an existing account/)).toBeInTheDocument()
  })

  it("creates the selected role and shows the safe receipt only", async () => {
    const stub = stubProvision()
    renderAuthenticated(<AdminUsersPage />, { account: adminAccountFixture() })
    const user = userEvent.setup()

    await user.type(screen.getByLabelText("Email"), "newdev@example.com")
    await user.type(screen.getByLabelText("Password"), "correct-horse-battery-99")
    await user.type(screen.getByLabelText("Confirm password"), "correct-horse-battery-99")
    await user.selectOptions(screen.getByLabelText("Account role"), "developer")
    await user.click(screen.getByRole("button", { name: "Create account" }))

    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(
        "Created the Developer account newdev@example.com.",
      )
    })
    expect(screen.getByText("newdev@example.com")).toBeInTheDocument()
    expect(screen.getByText("developer")).toBeInTheDocument()
    const posts = stub.requestsTo("/api/v1/users")
    expect(posts).toHaveLength(1)
    expect(posts[0]?.body).toEqual({
      email: "newdev@example.com",
      password: "correct-horse-battery-99",
      role: "developer",
    })
  })

  it("shows an alert when the passwords do not match", async () => {
    const stub = stubProvision()
    renderAuthenticated(<AdminUsersPage />, { account: adminAccountFixture() })
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
    renderAuthenticated(<AdminUsersPage />, { account: adminAccountFixture() })
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

  it("restricts the screen for a developer account", () => {
    renderAuthenticated(<AdminUsersPage />, {
      account: developerAccountFixture(),
    })

    expect(
      screen.getByRole("heading", { name: "Account roles" }),
    ).toBeInTheDocument()
    expect(screen.getByRole("status")).toHaveTextContent(
      "available to Admin accounts only",
    )
    expect(screen.queryByRole("textbox")).toBeNull()
    expect(screen.queryByRole("combobox")).toBeNull()
    expect(
      screen.queryByRole("button", { name: "Create account" }),
    ).toBeNull()
  })

  it("restricts the screen for an agent account", () => {
    renderAuthenticated(<AdminUsersPage />, { account: agentAccountFixture() })

    expect(
      screen.getByRole("heading", { name: "Account roles" }),
    ).toBeInTheDocument()
    expect(screen.getByRole("status")).toHaveTextContent(
      "available to Admin accounts only",
    )
    expect(screen.queryByRole("textbox")).toBeNull()
    expect(screen.queryByRole("combobox")).toBeNull()
    expect(
      screen.queryByRole("button", { name: "Create account" }),
    ).toBeNull()
  })

  it("restricts the screen for an anonymous visitor", () => {
    renderAuthenticated(<AdminUsersPage />, { account: null })

    expect(
      screen.getByRole("heading", { name: "Account roles" }),
    ).toBeInTheDocument()
    expect(screen.getByRole("status")).toHaveTextContent(
      "available to Admin accounts only",
    )
    expect(screen.queryByRole("textbox")).toBeNull()
    expect(screen.queryByRole("combobox")).toBeNull()
    expect(
      screen.queryByRole("button", { name: "Create account" }),
    ).toBeNull()
  })
})
