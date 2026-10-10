import { describe, it, expect, afterEach, vi } from "vitest"
import { render, screen } from "@testing-library/react"
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
  it("shows the account name and the username in the expanded row", () => {
    // SB4-ROLE: the outside row shows the account role, not the email.
    renderMenu(adminAccountFixture({ email: "lead@example.com" }))

    const trigger = screen.getByRole("button", { name: "Open user menu" })
    expect(trigger).toHaveTextContent("lead")
    expect(trigger).toHaveTextContent("Admin")
    expect(trigger).not.toHaveTextContent("lead@example.com")
  })

  it("shows both approved identity values and Sign out in the popup", async () => {
    const user = userEvent.setup()
    renderMenu(adminAccountFixture())

    await openPopup(user)

    const dialog = screen.getByRole("dialog", { name: "User account" })
    expect(dialog).toHaveTextContent("admin")
    expect(dialog).toHaveTextContent("admin@example.com")
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
  it("uses a size-8 avatar with centered letter classes outside", () => {
    renderMenu(adminAccountFixture())

    const trigger = screen.getByRole("button", { name: "Open user menu" })
    const avatar = trigger.querySelector('span[aria-hidden="true"]')
    expect(avatar).not.toBeNull()
    for (const token of ["size-8", "grid", "place-items-center", "leading-none", "rounded-full"]) {
      expect(avatar?.classList.contains(token)).toBe(true)
    }
    expect(avatar?.textContent).toBe("A")
  })

  it("uses a size-10 avatar with centered letter classes inside the popup", async () => {
    const user = userEvent.setup()
    renderMenu(adminAccountFixture())

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
    expect(divider.classList.contains("mb-1")).toBe(true)
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
  ])("shows role outside and email inside for %s", async (_role, account) => {
    // SB4-ROLE: username and role outside, username and email inside.
    const user = userEvent.setup()
    renderMenu(account)

    const trigger = screen.getByRole("button", { name: "Open user menu" })
    expect(trigger.textContent).not.toContain(account.email)

    await openPopup(user)

    const dialog = screen.getByRole("dialog", { name: "User account" })
    expect(dialog).toHaveTextContent(account.email)
  })

  it("shows the role outside and the full email inside for long identity text", async () => {
    const user = userEvent.setup()
    const account = adminAccountFixture({
      email: "very-long-identity-local-part-that-must-truncate@example.com",
    })
    renderMenu(account)

    const trigger = screen.getByRole("button", { name: "Open user menu" })
    expect(trigger).toHaveTextContent("very-long-identity-local-part-that-must-truncate")
    expect(trigger).toHaveTextContent("Admin")
    expect(trigger.textContent).not.toContain(
      "very-long-identity-local-part-that-must-truncate@example.com"
    )

    await openPopup(user)

    expect(screen.getByRole("dialog", { name: "User account" })).toHaveTextContent(
      "very-long-identity-local-part-that-must-truncate@example.com"
    )
  })
})
