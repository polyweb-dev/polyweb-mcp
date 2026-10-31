import { expect, type Page, type Route } from "@playwright/test"
import { Given, When, Then } from "./fixtures"
import { setStubbedSystemPermissions } from "./backendStub"
import {
  ROLE_LABEL_PATTERN,
  SYSTEM_ADMIN_PERMISSIONS,
  type StubUserAccount,
  userAccountBody,
} from "./accountStub"

/**
 * Sidebar account menu acceptance (PLAN Sections 25 and 30, B1-B13 and R1-R8),
 * rewritten to the permission model (TASK-000046 U1).
 *
 * Each scenario uses a scenario-local auth stub: POST /auth/jwt/refresh
 * returns one browser access projection, GET /users/me returns a role-less
 * account, DELETE /auth/jwt/refresh answers the logout. The account carries no
 * role: every navigation gate follows the system permissions served by
 * GET /api/v1/system/access (backendStub.ts), set per account kind below. The
 * shared deterministic backend stub (fixtures.ts Before hook) serves all data
 * routes. No step sleeps.
 */

const ACCESS_BODY = {
  access_token: "stub-access-token",
  token_type: "bearer",
  expires_in: 900,
  refresh_expires_in: 604800,
}

const LONG_EMAIL = "very-long-identity-local-part-that-must-truncate@example.com"
const LONG_LOCAL_PART = LONG_EMAIL.slice(0, LONG_EMAIL.indexOf("@"))

/**
 * Account kinds of the sidebar scenarios. `name` is the display name the UI
 * must show: "first last" when present, otherwise the username.
 */
interface SidebarAccount {
  body: StubUserAccount
  name: string
  systemPermissions: readonly string[]
}

const SIDEBAR_ACCOUNTS: Record<string, SidebarAccount> = {
  // Every system permission: Routing, Usage, Settings, edits and Admin.
  "system administrator": {
    body: userAccountBody("11111111-1111-4111-8111-111111111111", "admin@example.com", {
      username: "admin",
    }),
    name: "admin",
    systemPermissions: SYSTEM_ADMIN_PERMISSIONS,
  },
  // Read-only control access: Routing, Usage and Settings, no edits, no Admin.
  "settings reader": {
    body: userAccountBody("22222222-2222-4222-8222-222222222222", "reader@example.com", {
      username: "reader",
    }),
    name: "reader",
    systemPermissions: ["system.settings.read"],
  },
  // No system permission at all: Playground, Activity, Projects, Account only.
  member: {
    body: userAccountBody("33333333-3333-4333-8333-333333333333", "member@example.com", {
      first_name: "Ada",
      last_name: "Lovelace",
    }),
    name: "Ada Lovelace",
    systemPermissions: [],
  },
  "long-identity": {
    body: userAccountBody("44444444-4444-4444-8444-444444444444", LONG_EMAIL, {
      username: LONG_LOCAL_PART,
    }),
    name: LONG_LOCAL_PART,
    systemPermissions: SYSTEM_ADMIN_PERMISSIONS,
  },
}

/** Session-storage key that tells later steps which account kind is signed in. */
const ACCOUNT_KEY = "sidebar-test-account"

type LogoutMode = "success" | "pending" | "failure"

let logoutMode: LogoutMode = "success"
let logoutRequests = 0

function sidebarAccount(kind: string): SidebarAccount {
  const account = SIDEBAR_ACCOUNTS[kind]
  if (account === undefined) throw new Error(`unknown sidebar account kind: ${kind}`)
  return account
}

async function currentAccount(page: Page): Promise<SidebarAccount> {
  const kind = await page.evaluate((key) => window.sessionStorage.getItem(key), ACCOUNT_KEY)
  return sidebarAccount(kind ?? "system administrator")
}

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  })
}

async function installSidebarAuth(page: Page, kind: string): Promise<void> {
  const account = sidebarAccount(kind)
  logoutMode = "success"
  logoutRequests = 0
  setStubbedSystemPermissions(account.systemPermissions)
  await page.unroute("**/auth/jwt/refresh").catch(() => {})
  await page.unroute("**/users/me").catch(() => {})
  await page.route("**/auth/jwt/refresh", (route) => {
    const method = route.request().method()
    if (method === "POST") return json(route, ACCESS_BODY)
    if (method === "DELETE") {
      logoutRequests += 1
      if (logoutMode === "failure") return json(route, { detail: "logout boom" }, 500)
      if (logoutMode === "pending") {
        return new Promise<void>((resolve) => {
          setTimeout(() => {
            void json(route, null, 204).then(() => resolve())
          }, 400)
        })
      }
      return json(route, null, 204)
    }
    return route.fallback()
  })
  await page.route("**/users/me", (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    return json(route, account.body)
  })
  await page.addInitScript(
    ([key, value]) => {
      window.sessionStorage.setItem(key as string, value as string)
    },
    [ACCOUNT_KEY, kind]
  )
}

function userMenuTrigger(page: Page): ReturnType<Page["getByRole"]> {
  return page.getByRole("button", { name: "Open user menu", exact: true })
}

function accountDialog(page: Page): ReturnType<Page["getByRole"]> {
  return page.getByRole("dialog", { name: "User account" })
}

async function openWorkspace(page: Page, path: string): Promise<void> {
  await page.goto(path)
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible({
    timeout: 15_000,
  })
}

Given("the sidebar session belongs to a system administrator", async ({ page }) => {
  await installSidebarAuth(page, "system administrator")
})

Given("the sidebar session belongs to the {string} account", async ({ page }, kind: string) => {
  await installSidebarAuth(page, kind)
})

Given("the sidebar session belongs to the long-identity account", async ({ page }) => {
  await installSidebarAuth(page, "long-identity")
})

Given(
  "the sidebar logout stays pending for the double-action check",
  async () => {
    logoutMode = "pending"
  }
)

Given("the sidebar logout succeeds for the outcome check", async () => {
  logoutMode = "success"
})

Given("the sidebar logout fails safely for the outcome check", async () => {
  logoutMode = "failure"
})

When("I open the playground workspace for the sidebar check", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openWorkspace(page, "/playground")
})

When(
  "I open the playground workspace for the sidebar check at short height",
  async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 400 })
    await openWorkspace(page, "/playground")
  }
)

When("I open the account workspace for the sidebar check", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openWorkspace(page, "/account")
  await expect(page.getByRole("heading", { name: "Account", exact: true })).toBeVisible()
})

When("I activate the expanded account row", async ({ page }) => {
  await userMenuTrigger(page).click()
  await expect(accountDialog(page)).toBeVisible()
})

When("I collapse the sidebar for the account check", async ({ page }) => {
  await page.getByRole("button", { name: "Collapse sidebar", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "Expand sidebar", exact: true })
  ).toBeVisible()
})

When("I activate the collapsed account avatar", async ({ page }) => {
  await userMenuTrigger(page).click()
  await expect(accountDialog(page)).toBeVisible()
})

When("I dismiss the account popup with Escape", async ({ page }) => {
  await page.keyboard.press("Escape")
})

When("I dismiss the account popup with an outside click", async ({ page }) => {
  await page.getByRole("link", { name: "Routing", exact: true }).click()
})

When("I toggle the account popup with the trigger", async ({ page }) => {
  await userMenuTrigger(page).click()
})

When("I open the mobile navigation drawer for the account check", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole("button", { name: "Open navigation", exact: true }).click()
  await expect(page.getByRole("dialog", { name: "Navigation" })).toBeVisible()
})

When("I activate the drawer account row", async ({ page }) => {
  const drawer = page.getByRole("dialog", { name: "Navigation" })
  await drawer.getByRole("button", { name: "Open user menu", exact: true }).click()
  await expect(accountDialog(page)).toBeVisible()
})

When("I press Escape once for the nested popup", async ({ page }) => {
  await page.keyboard.press("Escape")
})

When("I press Escape again for the drawer", async ({ page }) => {
  await page.keyboard.press("Escape")
})

When("I follow the Routing link with an open popup", async ({ page }) => {
  await page.getByRole("link", { name: "Routing", exact: true }).click()
})

When("I toggle sidebar mode with an open popup", async ({ page }) => {
  const collapse = page.getByRole("button", { name: "Collapse sidebar", exact: true })
  if (await collapse.isVisible()) {
    await collapse.click()
    return
  }
  await page.getByRole("button", { name: "Expand sidebar", exact: true }).click()
})

When("I choose Sign out twice while logout stays pending", async ({ page }) => {
  const signOut = page.getByRole("button", { name: "Sign out", exact: true })
  await signOut.click()
  await expect(signOut).toBeDisabled()
  await signOut.click({ timeout: 1_000 }).catch(() => {})
})

When("I choose Sign out for the outcome check", async ({ page }) => {
  await page.getByRole("button", { name: "Sign out", exact: true }).click()
})

/** Every Primary link of a system administrator, in contract order. */
const ALL_PRIMARY_LINKS: Array<[string, string]> = [
  ["Playground", "/playground"],
  ["Routing", "/routing"],
  ["Usage", "/usage"],
  ["Activity", "/activity"],
  ["Settings", "/settings"],
  ["Projects", "/projects"],
  ["Account", "/account"],
  ["Admin", "/admin/users"],
]

async function expectPrimaryLinks(page: Page, labels: string[]): Promise<void> {
  const links = page.getByRole("navigation", { name: "Primary" }).getByRole("link")
  await expect(links).toHaveCount(labels.length)
  for (const [index, label] of labels.entries()) {
    await expect(links.nth(index)).toHaveAccessibleName(label)
  }
}

Then("the sidebar shows eight links in order with exact hrefs", async ({ page }) => {
  const nav = page.getByRole("navigation", { name: "Primary" })
  await expectPrimaryLinks(
    page,
    ALL_PRIMARY_LINKS.map(([label]) => label)
  )
  for (const [label, href] of ALL_PRIMARY_LINKS) {
    await expect(nav.getByRole("link", { name: label, exact: true })).toHaveAttribute(
      "href",
      href
    )
  }
})

Then("the Primary navigation lists exactly {string}", async ({ page }, list: string) => {
  await expectPrimaryLinks(
    page,
    list.split(",").map((label) => label.trim())
  )
})

Then("the sidebar shows the Account and Admin links", async ({ page }) => {
  const nav = page.getByRole("navigation", { name: "Primary" })
  await expect(nav.getByRole("link", { name: "Account", exact: true })).toBeVisible()
  await expect(nav.getByRole("link", { name: "Admin", exact: true })).toBeVisible()
})

Then("the sidebar shows {int} links without Admin", async ({ page }, count: number) => {
  const nav = page.getByRole("navigation", { name: "Primary" })
  await expect(nav.getByRole("link")).toHaveCount(count)
})

Then("the sidebar shows no Admin link", async ({ page }) => {
  await expect(
    page.getByRole("link", { name: "Admin", exact: true })
  ).toHaveCount(0)
})

Then(
  "the account popup shows the approved identity values and Sign out",
  async ({ page }) => {
    const { name, body } = await currentAccount(page)
    const dialog = accountDialog(page)
    await expect(dialog).toBeVisible()
    await expect(dialog.getByText(name, { exact: true }).first()).toBeVisible()
    await expect(dialog.getByText(body.email, { exact: true }).first()).toBeVisible()
    // No role or account-type label: authority is never a property of the account.
    expect((await dialog.textContent()) ?? "").not.toMatch(ROLE_LABEL_PATTERN)
    await expect(
      page.getByRole("button", { name: "Sign out", exact: true })
    ).toHaveCount(1)
    await expect(
      page.getByRole("button", { name: "Sign out", exact: true })
    ).toBeVisible()
  }
)

Then("the sidebar shows no separate Sign out button", async ({ page }) => {
  const aside = page.locator("aside")
  await expect(
    aside.getByRole("button", { name: "Sign out", exact: true })
  ).toHaveCount(0)
})

Then("the collapsed trigger keeps a complete accessible name", async ({ page }) => {
  const trigger = userMenuTrigger(page)
  await expect(trigger).toHaveAttribute("aria-label", "Open user menu")
  const { body } = await currentAccount(page)
  await expect(trigger).toHaveAttribute("title", body.email)
})

Then("the account popup closes and trigger focus returns", async ({ page }) => {
  await expect(accountDialog(page)).toHaveCount(0)
  await expect(userMenuTrigger(page)).toBeFocused()
})

Then("the account popup closes and destination focus stays", async ({ page }) => {
  await expect(accountDialog(page)).toHaveCount(0)
  await expect(page.getByRole("link", { name: "Routing", exact: true })).toBeFocused()
})

Then("the account popup closes", async ({ page }) => {
  await expect(accountDialog(page)).toHaveCount(0)
})

Then("the account popup stays above the drawer", async ({ page }) => {
  await expect(page.getByRole("dialog", { name: "Navigation" })).toBeVisible()
  const dialog = accountDialog(page)
  await expect(dialog).toBeVisible()
  const positioner = page.locator(".z-60")
  await expect(positioner).toHaveCount(1)
  const box = await dialog.boundingBox()
  expect(box).not.toBeNull()
  const viewport = page.viewportSize()
  expect(viewport).not.toBeNull()
  if (box !== null && viewport !== null) {
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.y).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(viewport.width)
    expect(box.y + box.height).toBeLessThanOrEqual(viewport.height)
  }
})

Then("only the account popup closes", async ({ page }) => {
  await expect(accountDialog(page)).toHaveCount(0)
  await expect(page.getByRole("dialog", { name: "Navigation" })).toBeVisible()
})

Then("the drawer closes and Open navigation keeps focus", async ({ page }) => {
  await expect(page.getByRole("dialog", { name: "Navigation" })).toHaveCount(0)
  await expect(
    page.getByRole("button", { name: "Open navigation", exact: true })
  ).toBeFocused()
})

Then("each permitted sidebar link keeps its route and view", async ({ page }) => {
  const expected: Array<{ link: string; heading: string; path: string }> = [
    { link: "Playground", heading: "Search Playground", path: "/playground" },
    { link: "Routing", heading: "Routing", path: "/routing" },
    { link: "Usage", heading: "Usage", path: "/usage" },
    { link: "Activity", heading: "Activity", path: "/activity" },
    { link: "Settings", heading: "Settings", path: "/settings" },
    { link: "Projects", heading: "Projects", path: "/projects" },
    { link: "Account", heading: "Account", path: "/account" },
  ]
  for (const { link, heading, path } of expected) {
    await page.getByRole("link", { name: link, exact: true }).click()
    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible()
    expect(new URL(page.url()).pathname).toBe(path)
  }
  // Admin: the account-creation view renders with its "Accounts" heading and
  // its creation form.
  await page.getByRole("link", { name: "Admin", exact: true }).click()
  await expect(page.getByRole("heading", { name: "Accounts", exact: true })).toBeVisible()
  await expect(page.getByRole("button", { name: "Create account", exact: true })).toBeVisible()
  expect(new URL(page.url()).pathname).toBe("/admin/users")
})

Then("mobile navigation still closes the drawer on follow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole("button", { name: "Open navigation", exact: true }).click()
  const drawer = page.getByRole("dialog", { name: "Navigation" })
  await expect(drawer).toBeVisible()
  await drawer.getByRole("link", { name: "Routing", exact: true }).click()
  await expect(page.getByRole("dialog", { name: "Navigation" })).toHaveCount(0)
  expect(new URL(page.url()).pathname).toBe("/routing")
})

Then("the sidebar sends one logout operation", async ({ page }) => {
  await expect(page.getByRole("heading", { name: "Sign in", exact: true })).toBeVisible({
    timeout: 15_000,
  })
  expect(logoutRequests).toBe(1)
})

Then("the Sign out action stays disabled until completion", async ({ page }) => {
  await expect(page.getByRole("heading", { name: "Sign in", exact: true })).toBeVisible({
    timeout: 15_000,
  })
  expect(logoutRequests).toBe(1)
  void page
})

Then("the sidebar logout outcome is session exit", async ({ page }) => {
  await expect(
    page.getByRole("heading", { name: "Sign in", exact: true })
  ).toBeVisible({ timeout: 15_000 })
  expect(logoutRequests).toBe(1)
})

Then("the failed logout keeps a safe session exit", async ({ page }) => {
  await expect(
    page.getByRole("heading", { name: "Sign in", exact: true })
  ).toBeVisible({ timeout: 15_000 })
  expect(logoutRequests).toBe(1)
  const bodyText = (await page.locator("body").textContent()) ?? ""
  expect(bodyText).not.toContain("stub-access-token")
  expect(bodyText).not.toMatch(/refresh_token/i)
  expect(bodyText).not.toContain("logout boom")
})

Then("navigation scrolls and the account row stays accessible", async ({ page }) => {
  const nav = page.getByRole("navigation", { name: "Primary" })
  const overflowY = await nav.evaluate(
    (element) => getComputedStyle(element).overflowY
  )
  expect(overflowY).toBe("auto")
  await expect(userMenuTrigger(page)).toBeVisible()
})

Then("the account popup stays within the viewport", async ({ page }) => {
  await userMenuTrigger(page).click()
  const dialog = accountDialog(page)
  await expect(dialog).toBeVisible()
  const box = await dialog.boundingBox()
  expect(box).not.toBeNull()
  const viewport = page.viewportSize()
  expect(viewport).not.toBeNull()
  if (box !== null && viewport !== null) {
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.y).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(viewport.width)
    expect(box.y + box.height).toBeLessThanOrEqual(viewport.height)
  }
})

Then("the account popup closes without stale identity", async ({ page }) => {
  await expect(accountDialog(page)).toHaveCount(0)
})

Then("the account page keeps facts without Sign out", async ({ page }) => {
  const { body } = await currentAccount(page)
  await expect(page.getByText(body.email, { exact: true }).first()).toBeVisible()
  await expect(
    page.getByRole("button", { name: "Sign out", exact: true })
  ).toHaveCount(0)
})

Then("the account page shows no role", async ({ page }) => {
  const main = page.locator("main")
  await expect(main.getByText("Role", { exact: true })).toHaveCount(0)
  expect((await main.textContent()) ?? "").not.toMatch(ROLE_LABEL_PATTERN)
})

Then(
  "the account creation link follows system.settings.write for the {string} account",
  async ({ page }, kind: string) => {
    const link = page.getByRole("link", { name: "Create accounts" })
    if (sidebarAccount(kind).systemPermissions.includes("system.settings.write")) {
      await expect(link).toBeVisible()
      await expect(link).toHaveAttribute("href", "/admin/users")
      return
    }
    await expect(link).toHaveCount(0)
  }
)

When("I open the gated page {string} for the sidebar check", async ({ page }, path: string) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto(path)
})

Then("the gated page redirects home to the projects list", async ({ page }) => {
  // An unauthorized direct URL redirects to "/", which lands on the last
  // project or, with none stored, on /projects.
  await expect(page.getByRole("heading", { name: "Projects", exact: true })).toBeVisible({
    timeout: 15_000,
  })
  expect(new URL(page.url()).pathname).toBe("/projects")
  await expect(page.getByRole("button", { name: "Create account", exact: true })).toHaveCount(0)
  await expect(page.getByRole("heading", { name: "Accounts", exact: true })).toHaveCount(0)
})

function expansionButton(page: Page): ReturnType<Page["getByRole"]> {
  return page.getByRole("button", { name: "Expand sidebar", exact: true })
}

async function rootPixels(page: Page): Promise<number> {
  return page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).fontSize))
}

Then("the outside and popup avatars use larger centered circles", async ({ page }) => {
  const trigger = userMenuTrigger(page)
  const outside = trigger.locator('span[aria-hidden="true"]')
  await expect(outside).toHaveCount(1)
  for (const token of ["size-8", "grid", "place-items-center", "leading-none", "rounded-full"]) {
    await expect(outside).toHaveClass(new RegExp(`(^| )${token}( |$)`))
  }
  const outsideBox = await outside.boundingBox()
  expect(outsideBox).not.toBeNull()
  const root = await rootPixels(page)
  expect(outsideBox?.width).toBe(2 * root)
  expect(outsideBox?.height).toBe(2 * root)
  await expect(outside).toHaveText(/^[A-Z?\]]$/)

  const dialog = accountDialog(page)
  const popup = dialog.locator('span[aria-hidden="true"]')
  await expect(popup).toHaveCount(1)
  for (const token of ["size-10", "grid", "place-items-center", "leading-none", "rounded-full"]) {
    await expect(popup).toHaveClass(new RegExp(`(^| )${token}( |$)`))
  }
  const popupBox = await popup.boundingBox()
  expect(popupBox).not.toBeNull()
  expect(popupBox?.width).toBe(2.5 * root)
  expect(popupBox?.height).toBe(2.5 * root)
  await expect(popup).toHaveText(/^[A-Z?\]]$/)
})

Then("the idle collapsed header shows the logo", async ({ page }) => {
  const button = expansionButton(page)
  await expect(button).toBeVisible()
  await expect(button.locator("img")).toBeVisible()
  await expect(button.locator("span.col-start-1")).toHaveCSS("opacity", "1")
  await expect(button.locator("svg")).toHaveCSS("opacity", "0")
})

When("I rest the pointer on the expansion control", async ({ page }) => {
  await expansionButton(page).hover()
})

Then("the expansion icon appears without geometry movement", async ({ page }) => {
  const button = expansionButton(page)
  const before = await button.boundingBox()
  await button.hover()
  await expect(button.locator("svg")).toBeVisible()
  await expect(button.locator("svg")).toHaveCSS("opacity", "1")
  await expect(button.locator("span.col-start-1")).toHaveCSS("opacity", "0")
  const after = await button.boundingBox()
  expect(after).toEqual(before)
})

When("I focus the expansion control with the keyboard", async ({ page }) => {
  await page.keyboard.press("Tab")
  await expect(expansionButton(page)).toBeFocused()
})

Then("keyboard focus reveals the expansion control", async ({ page }) => {
  const button = expansionButton(page)
  await expect(button).toBeFocused()
  await expect(button.locator("svg")).toHaveCSS("opacity", "1")
})

When("I press Enter on the focused expansion control", async ({ page }) => {
  await expect(expansionButton(page)).toBeFocused()
  await page.keyboard.press("Enter")
})

When("I press Space on the focused expansion control", async ({ page }) => {
  await expect(expansionButton(page)).toBeFocused()
  await page.keyboard.press("Space")
})

Then("the rail expands with the adjacent collapse control", async ({ page }) => {
  const collapse = page.getByRole("button", { name: "Collapse sidebar", exact: true })
  await expect(collapse).toBeVisible()
  await expect(
    page.getByRole("button", { name: "Expand sidebar", exact: true })
  ).toHaveCount(0)
  const aside = page.locator("aside")
  expect(await aside.getAttribute("class")).not.toMatch(/w-16/)
})

When("I activate the logo button without hover", async ({ page }) => {
  await expansionButton(page).dispatchEvent("click")
})

Then(
  "one inset divider sits above the outside row with gaps at both ends",
  async ({ page }) => {
    const aside = page.locator("aside")
    const divider = aside.locator("div.mx-2")
    await expect(divider).toHaveCount(1)
    for (const token of ["mb-1", "h-px"]) {
      await expect(divider).toHaveClass(new RegExp(`(^| )${token}( |$)`))
    }
    await expect(divider).toHaveAttribute("aria-hidden", "true")
    const dividerBox = await divider.boundingBox()
    const triggerBox = await userMenuTrigger(page).boundingBox()
    const asideBox = await aside.boundingBox()
    expect(dividerBox).not.toBeNull()
    expect(triggerBox).not.toBeNull()
    expect(asideBox).not.toBeNull()
    if (dividerBox !== null && triggerBox !== null && asideBox !== null) {
      expect(dividerBox.y + dividerBox.height).toBeLessThanOrEqual(triggerBox.y)
      expect(dividerBox.x).toBeGreaterThan(asideBox.x)
      expect(dividerBox.x + dividerBox.width).toBeLessThan(asideBox.x + asideBox.width)
    }
  }
)

Then("no divider separates the outside identity lines", async ({ page }) => {
  await expect(userMenuTrigger(page).locator("div.h-px")).toHaveCount(0)
})

Then("the drawer account row keeps the same inset divider", async ({ page }) => {
  const drawer = page.getByRole("dialog", { name: "Navigation" })
  await expect(drawer).toBeVisible()
  const divider = drawer.locator("div.mx-2")
  await expect(divider).toHaveCount(1)
  for (const token of ["mb-1", "h-px"]) {
    await expect(divider).toHaveClass(new RegExp(`(^| )${token}( |$)`))
  }
  const dividerBox = await divider.boundingBox()
  const triggerBox = await drawer
    .getByRole("button", { name: "Open user menu", exact: true })
    .boundingBox()
  expect(dividerBox).not.toBeNull()
  expect(triggerBox).not.toBeNull()
  if (dividerBox !== null && triggerBox !== null) {
    expect(dividerBox.y + dividerBox.height).toBeLessThanOrEqual(triggerBox.y)
  }
})

Then("the outside row shows the display name and email without a role", async ({ page }) => {
  const { name, body } = await currentAccount(page)
  const trigger = userMenuTrigger(page)
  await expect(trigger).toBeVisible()
  // Display name: "first last" when present, otherwise the username.
  await expect(trigger).toContainText(name)
  await expect(trigger).toContainText(body.email)
  expect((await trigger.textContent()) ?? "").not.toMatch(ROLE_LABEL_PATTERN)
})

Then("the sidebar keeps the stored collapse choice", async ({ page }) => {
  await expect(expansionButton(page)).toBeVisible()
  const aside = page.locator("aside")
  expect(await aside.getAttribute("class")).toMatch(/w-16/)
})

When("I open the compact workspace at 320 pixels", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 400 })
  await page.goto("/playground")
  await expect(
    page.getByRole("button", { name: "Open navigation", exact: true })
  ).toBeVisible({ timeout: 15_000 })
})

Then("the document has no horizontal overflow at 320 pixels", async ({ page }) => {
  const overflow = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    inner: window.innerWidth,
  }))
  expect(overflow.scroll).toBeLessThanOrEqual(overflow.inner)
  await expect(userMenuTrigger(page)).toHaveCount(0)
})

When("I open the navigation drawer without viewport change", async ({ page }) => {
  await page.getByRole("button", { name: "Open navigation", exact: true }).click()
  await expect(page.getByRole("dialog", { name: "Navigation" })).toBeVisible()
})
