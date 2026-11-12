import { describe, it, expect, afterEach, vi } from "vitest"
import { cleanup, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router"
import { SidebarAccountMenu } from "./SidebarAccountMenu"
import { AuthContext } from "@/domains/auth/state/context"
import { authenticatedContextValue } from "@/test/renderAuthenticated"
import {
  TEST_ACCESS_TOKEN,
  adminAccountFixture,
  agentAccountFixture,
  developerAccountFixture,
} from "@/test/authFixtures"
import { ApiError } from "@/shared/api/http"
import type { UserAccount } from "@/domains/auth"

function renderMenu(account: UserAccount | null, collapsed = false) {
  return render(
    <MemoryRouter initialEntries={["/playground"]}>
      <AuthContext.Provider value={authenticatedContextValue(account)}>
        <SidebarAccountMenu collapsed={collapsed} />
      </AuthContext.Provider>
    </MemoryRouter>
  )
}

function renderMenuWithLogout(
  account: UserAccount | null,
  logout: () => Promise<void>,
  collapsed = false
) {
  return render(
    <MemoryRouter initialEntries={["/playground"]}>
      <AuthContext.Provider
        value={authenticatedContextValue(account, { logout })}
      >
        <SidebarAccountMenu collapsed={collapsed} />
      </AuthContext.Provider>
    </MemoryRouter>
  )
}

async function openPopup(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Open user menu" }))
  await screen.findByRole("dialog", { name: "User account" })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("SidebarAccountMenu identity", () => {
  it("shows the email and no role text in the expanded row of an unnamed account", () => {
    renderMenu(adminAccountFixture({ email: "lead@example.com" }))

    const trigger = screen.getByRole("button", { name: "Open user menu" })
    expect(trigger).toHaveTextContent("lead@example.com")
    expect(trigger.textContent ?? "").not.toMatch(/Admin|Developer|Agent/)
  })

  it("shows the full name above the email when the account has one", async () => {
    const user = userEvent.setup()
    renderMenu(
      adminAccountFixture({ email: "ada@example.com", first_name: "Ada", last_name: "Lovelace", username: "ada" })
    )

    const trigger = screen.getByRole("button", { name: "Open user menu" })
    expect(trigger).toHaveTextContent("Ada Lovelace")
    expect(trigger).toHaveTextContent("ada@example.com")

    // The expanded row already names the account; the popup does not repeat it.
    await openPopup(user)
    const dialog = screen.getByRole("dialog", { name: "User account" })
    expect(dialog).not.toHaveTextContent("Ada Lovelace")
    expect(dialog).not.toHaveTextContent("ada@example.com")
  })

  it("shows the username when the account has no full name", () => {
    renderMenu(adminAccountFixture({ email: "ops@example.com", username: "ops-lead" }))

    const trigger = screen.getByRole("button", { name: "Open user menu" })
    expect(trigger).toHaveTextContent("ops-lead")
    expect(trigger).toHaveTextContent("ops@example.com")
  })

  it("shows only Account and Sign out in the expanded popup", async () => {
    const user = userEvent.setup()
    renderMenu(adminAccountFixture())

    await openPopup(user)

    const dialog = screen.getByRole("dialog", { name: "User account" })
    expect(dialog).not.toHaveTextContent("admin@example.com")
    expect(within(dialog).getByRole("link", { name: "Account" })).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Sign out" })
    ).toBeInTheDocument()
  })

  it("renders nothing when the account is null", () => {
    const { container } = renderMenu(null)

    expect(container.firstChild).toBeNull()
    expect(
      screen.queryByRole("button", { name: "Open user menu" })
    ).not.toBeInTheDocument()
  })
})

describe("SidebarAccountMenu collapsed access", () => {
  it("keeps a complete accessible name and title on the collapsed avatar", () => {
    renderMenu(adminAccountFixture(), true)

    const trigger = screen.getByRole("button", { name: "Open user menu" })
    expect(trigger).toHaveAttribute("aria-label", "Open user menu")
    expect(trigger).toHaveAttribute("title", "admin@example.com")
    expect(trigger).toHaveTextContent("A")
  })

  it("opens the same popup from the collapsed avatar", async () => {
    const user = userEvent.setup()
    renderMenu(adminAccountFixture(), true)

    await openPopup(user)

    const dialog = screen.getByRole("dialog", { name: "User account" })
    expect(dialog).toHaveTextContent("admin")
    expect(dialog).toHaveTextContent("admin@example.com")
    expect(
      screen.getByRole("button", { name: "Sign out" })
    ).toBeInTheDocument()
  })
})

describe("SidebarAccountMenu keyboard and dismissal", () => {
  it("opens the popup on keyboard Enter", async () => {
    const user = userEvent.setup()
    renderMenu(adminAccountFixture())

    screen.getByRole("button", { name: "Open user menu" }).focus()
    await user.keyboard("{Enter}")

    expect(
      await screen.findByRole("dialog", { name: "User account" })
    ).toBeInTheDocument()
  })

  it("closes on Escape and returns focus to the trigger", async () => {
    const user = userEvent.setup()
    renderMenu(adminAccountFixture())

    await openPopup(user)
    await user.keyboard("{Escape}")

    expect(
      screen.queryByRole("dialog", { name: "User account" })
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Open user menu" })
    ).toHaveFocus()
  })

  it("toggles closed on a second trigger press", async () => {
    const user = userEvent.setup()
    renderMenu(adminAccountFixture())

    await openPopup(user)
    await user.click(screen.getByRole("button", { name: "Open user menu" }))

    expect(
      screen.queryByRole("dialog", { name: "User account" })
    ).not.toBeInTheDocument()
  })

  it("closes on outside click without stealing destination focus", async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={["/playground"]}>
        <AuthContext.Provider
          value={authenticatedContextValue(adminAccountFixture())}
        >
          <button type="button">Outside destination</button>
          <SidebarAccountMenu collapsed={false} />
        </AuthContext.Provider>
      </MemoryRouter>
    )

    await openPopup(user)
    await user.click(screen.getByRole("button", { name: "Outside destination" }))

    expect(
      screen.queryByRole("dialog", { name: "User account" })
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Outside destination" })
    ).toHaveFocus()
  })
})

describe("SidebarAccountMenu logout", () => {
  it("sends one logout operation on double action while pending", async () => {
    const user = userEvent.setup()
    let release!: () => void
    const pendingLogout = async (): Promise<void> => {
      await new Promise<void>((resolve) => { release = resolve })
    }
    const logout = vi.fn(pendingLogout)
    renderMenuWithLogout(adminAccountFixture(), logout)

    await openPopup(user)
    const signOut = screen.getByRole("button", { name: "Sign out" })
    await user.click(signOut)
    expect(signOut).toBeDisabled()
    await user.click(signOut).catch(() => {})
    expect(logout).toHaveBeenCalledTimes(1)

    release()
    await screen.findByRole("button", { name: "Open user menu" })
  })

  it("shows only safe text when logout rejects", async () => {
    const user = userEvent.setup()
    const failingLogout = async (): Promise<void> => {
      throw new ApiError(500, "logout boom", { detail: "logout boom" })
    }
    const logout = vi.fn(failingLogout)
    renderMenuWithLogout(adminAccountFixture(), logout)

    await openPopup(user)
    await user.click(screen.getByRole("button", { name: "Sign out" }))

    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent("logout boom")
    const bodyText = document.body.textContent ?? ""
    expect(bodyText).not.toContain(TEST_ACCESS_TOKEN)
    expect(bodyText).not.toMatch(/refresh_token/i)
    expect(logout).toHaveBeenCalledTimes(1)
  })

  it("holds no access or refresh credential text", async () => {
    const user = userEvent.setup()
    renderMenu(adminAccountFixture())

    await openPopup(user)

    expect(screen.queryByText(TEST_ACCESS_TOKEN)).toBeNull()
    const bodyText = document.body.textContent ?? ""
    expect(bodyText).not.toContain(TEST_ACCESS_TOKEN)
    expect(bodyText).not.toMatch(/refresh_token/i)
  })
})

describe("AccountPage.test.tsx", () => {
  it("calls logout when the Sign out button is clicked", async () => {
    const user = userEvent.setup()
    const logout = vi.fn(async () => {})
    renderMenuWithLogout(adminAccountFixture(), logout)

    await user.click(screen.getByRole("button", { name: "Open user menu" }))
    await user.click(screen.getByRole("button", { name: "Sign out" }))

    expect(logout).toHaveBeenCalledTimes(1)
  })
})

describe("SidebarAccountMenu SB4 refinements", () => {
  it("uses a size-7 avatar on the raised surface with centered letter classes outside", () => {
    renderMenu(adminAccountFixture())

    const trigger = screen.getByRole("button", { name: "Open user menu" })
    const avatar = trigger.querySelector('span[aria-hidden="true"]')
    expect(avatar).not.toBeNull()
    for (const token of [
      "size-7",
      "bg-[var(--raised)]",
      "grid",
      "place-items-center",
      "leading-none",
      "rounded-full",
    ]) {
      expect(avatar?.classList.contains(token)).toBe(true)
    }
    expect(avatar?.classList.contains("size-8")).toBe(false)
    expect(avatar?.textContent).toBe("A")
  })

  it("uses a size-10 avatar with centered letter classes inside the collapsed popup", async () => {
    const user = userEvent.setup()
    renderMenu(adminAccountFixture(), true)

    await openPopup(user)

    const dialog = screen.getByRole("dialog", { name: "User account" })
    const avatar = dialog.querySelector('span[aria-hidden="true"]')
    expect(avatar).not.toBeNull()
    for (const token of ["size-10", "grid", "place-items-center", "leading-none", "rounded-full"]) {
      expect(avatar?.classList.contains(token)).toBe(true)
    }
    expect(avatar?.textContent).toBe("A")
  })

  it("places one inset divider before the expanded trigger", () => {
    const { container } = renderMenu(adminAccountFixture())

    const dividers = container.querySelectorAll("div.mx-2")
    expect(dividers).toHaveLength(1)
    const divider = dividers[0]
    expect(divider.classList.contains("mb-2")).toBe(true)
    expect(divider.classList.contains("mb-1")).toBe(false)
    expect(divider.classList.contains("h-px")).toBe(true)
    expect(divider.getAttribute("aria-hidden")).toBe("true")
    const trigger = screen.getByRole("button", { name: "Open user menu" })
    expect(divider.compareDocumentPosition(trigger) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    )
  })

  it("shows no divider on the collapsed avatar-only row", () => {
    const { container } = renderMenu(adminAccountFixture(), true)

    expect(container.querySelectorAll("div.mx-2")).toHaveLength(0)
  })

  it.each<[string, UserAccount]>([
    ["admin", adminAccountFixture()],
    ["developer", developerAccountFixture()],
    ["agent", agentAccountFixture()],
  ])("shows the email outside and inside without role text for the %s persona", async (_persona, account) => {
    const user = userEvent.setup()
    renderMenu(account)

    const trigger = screen.getByRole("button", { name: "Open user menu" })
    expect(trigger).toHaveTextContent(account.email)
    expect(trigger.textContent ?? "").not.toMatch(/Admin|Developer|Agent/)
    cleanup()
    // Only the collapsed avatar row hides the email, so only its popup names the account.
    renderMenu(account, true)

    await openPopup(user)

    const dialog = screen.getByRole("dialog", { name: "User account" })
    expect(dialog).toHaveTextContent(account.email)
    expect(dialog.textContent ?? "").not.toMatch(/Admin|Developer|Agent/)
  })

  it("keeps the full long email in the truncating row and inside the collapsed popup", async () => {
    const user = userEvent.setup()
    const account = adminAccountFixture({
      email: "very-long-identity-local-part-that-must-truncate@example.com",
    })
    renderMenu(account)

    const trigger = screen.getByRole("button", { name: "Open user menu" })
    expect(trigger).toHaveTextContent(
      "very-long-identity-local-part-that-must-truncate@example.com"
    )
    expect(trigger.textContent ?? "").not.toMatch(/Admin/)
    cleanup()
    renderMenu(account, true)

    await openPopup(user)

    expect(screen.getByRole("dialog", { name: "User account" })).toHaveTextContent(
      "very-long-identity-local-part-that-must-truncate@example.com"
    )
  })
})

describe("SidebarAccountMenu named identity fallback", () => {
  it("shows the full name primary with the email secondary and the name initial", () => {
    renderMenu(
      adminAccountFixture({ email: "ada@example.com", first_name: "Ada", last_name: "Lovelace", username: "ada" })
    )

    const trigger = screen.getByRole("button", { name: "Open user menu" })
    expect(trigger).toHaveTextContent("Ada Lovelace")
    expect(trigger).toHaveTextContent("ada@example.com")
    const avatar = trigger.querySelector('span[aria-hidden="true"]')
    expect(avatar?.textContent).toBe("A")
    const nameLine = trigger.querySelector('span[title]')
    expect(nameLine?.getAttribute("title")).toBe("Ada Lovelace (ada@example.com)")
  })

  it("uses the username initial and the detail title on the collapsed avatar for a username-only account", () => {
    renderMenu(adminAccountFixture({ email: "ops@example.com", username: "zeta" }), true)

    const trigger = screen.getByRole("button", { name: "Open user menu" })
    expect(trigger).toHaveAttribute("title", "zeta (ops@example.com)")
    expect(trigger).toHaveTextContent("Z")
  })

  it("treats blank names as absent and shows the email alone", () => {
    renderMenu(
      adminAccountFixture({ email: "lead@example.com", first_name: "  ", last_name: " ", username: "  " })
    )

    const trigger = screen.getByRole("button", { name: "Open user menu" })
    expect(trigger).toHaveTextContent("lead@example.com")
    expect(trigger.textContent).not.toContain("(")
    const avatar = trigger.querySelector('span[aria-hidden="true"]')
    expect(avatar?.textContent).toBe("L")
  })
})
