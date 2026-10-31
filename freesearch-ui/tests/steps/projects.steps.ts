import { expect } from "@playwright/test"
import type { Page } from "@playwright/test"
import { Given, Then, When } from "./fixtures"
import { installBackendStub } from "./backendStub"
import { SYSTEM_ADMIN_PERMISSIONS, parsePermissionList, userAccountBody } from "./accountStub"
import {
  USER_ID,
  clearProjectStubMemberships,
  holdProjectStubMembers,
  installProjectStub,
  releaseProjectStubMembers,
  resetProjectStub,
  setProjectStubRoles,
  setProjectStubAccount,
} from "./projectStub"
import { secondTab, setSecondTab } from "./tabs"

const USER_EMAIL = "member@example.com"
const ALPHA_ID = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
const ALPHA_MEMBERS_URL = `/api/v1/projects/${ALPHA_ID}/members`

type AlphaOutcome = "aborted" | "responded" | "timeout"
const alphaOutcome: { value: Promise<AlphaOutcome> | null } = { value: null }
const ACCESS_BODY = {
  access_token: "project-stub-access",
  token_type: "bearer",
  expires_in: 900,
  refresh_expires_in: 604800,
}

async function json(route: import("@playwright/test").Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  })
}

async function installProjectAuth(page: Page): Promise<void> {
  await page.unroute("**/auth/jwt/refresh").catch(() => {})
  await page.unroute("**/users/me").catch(() => {})
  await page.route("**/auth/jwt/refresh", (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    return json(route, ACCESS_BODY)
  })
  await page.route("**/users/me", (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    // The backend account carries no role: authority is the system access
    // list served by the project stub plus the per-project access descriptor.
    return json(route, userAccountBody(USER_ID, USER_EMAIL))
  })
}

async function installAll(page: Page, systemPermissions: readonly string[] = []): Promise<void> {
  resetProjectStub()
  setProjectStubAccount(USER_EMAIL, systemPermissions)
  await installBackendStub(page)
  await installProjectStub(page)
  await installProjectAuth(page)
}

Given("the projects backend is stubbed", async ({ page }) => {
  await installAll(page)
})

Given("the projects backend is stubbed for a system administrator", async ({ page }) => {
  await installAll(page, SYSTEM_ADMIN_PERMISSIONS)
})

Given(
  "the projects backend is stubbed with system permissions {string}",
  async ({ page }, list: string) => {
    await installAll(page, parsePermissionList(list))
  }
)

Given("I am a member of project {word} with role {word}", async ({ page: _page }, name: string, role: string) => {
  setProjectStubRoles(name, [role])
})

Given("I hold no project memberships", async ({ page: _page }) => {
  clearProjectStubMemberships(USER_EMAIL)
})

Given("the members response for {word} is delayed", async ({ page }, name: string) => {
  holdProjectStubMembers(name)
  const seen = page
    .waitForRequest((req) => req.url().includes(ALPHA_MEMBERS_URL))
    .then(() => "seen" as const)
  const failed = page
    .waitForEvent("requestfailed", {
      predicate: (req) => req.url().includes(ALPHA_MEMBERS_URL),
    })
    .then(() => "aborted" as const)
  const finished = page
    .waitForResponse((res) => res.url().includes(ALPHA_MEMBERS_URL))
    .then(() => "responded" as const)
  alphaOutcome.value = Promise.all([seen, Promise.race([failed, finished])]).then(
    ([, outcome]) => outcome,
    () => "timeout" as const
  )
})

When("I open the workspace page {string}", async ({ page }, path: string) => {
  await page.goto(path)
})

When("I select project {word} from the project selector", async ({ page }, name: string) => {
  await page.getByRole("button", { name: "Select project" }).first().click()
  await page.getByRole("menuitem", { name, exact: false }).first().click()
})

When("I open a second tab on the workspace page {string}", async ({ page }, path: string) => {
  const context = page.context()
  const tab = await context.newPage()
  setSecondTab(tab)
  await installBackendStub(tab)
  await installProjectStub(tab)
  await installProjectAuth(tab)
  await tab.goto(path)
})

When("the project role in {word} is revoked", async ({ page: _page }, name: string) => {
  setProjectStubRoles(name, ["project_member"])
})

When("the delayed Alpha members request has settled", async ({ page: _page }) => {
  releaseProjectStubMembers()
  const outcome = await Promise.race([
    alphaOutcome.value ?? Promise.resolve("timeout" as const),
    new Promise<AlphaOutcome>((resolve) => setTimeout(() => resolve("timeout"), 10_000)),
  ])
  // Evidence for the report: "aborted" means the client cancelled the request
  // on the project switch; "responded" means it arrived late and was dropped.
  console.log(`[projects-shell] late Alpha members outcome: ${outcome}`)
  expect(outcome).not.toBe("timeout")
})

When("I focus both tabs again", async ({ page }) => {
  await page.evaluate(() => window.dispatchEvent(new Event("focus")))
  await secondTab().evaluate(() => window.dispatchEvent(new Event("focus")))
})

When("I type {string} into the field {string} of the second tab", async ({ page: _page }, value: string, label: string) => {
  await secondTab().getByLabel(label).fill(value)
})

Then("the members table shows {string}", async ({ page }, email: string) => {
  await expect(page.getByRole("cell", { name: email, exact: true })).toBeVisible({
    timeout: 15_000,
  })
})

Then("the members table does not show {string}", async ({ page }, email: string) => {
  await expect(page.getByRole("cell", { name: email, exact: true })).toBeHidden()
})

Then("the second tab shows the members table of {word}", async ({ page: _page }, _name: string) => {
  const tab = secondTab()
  await expect(tab.getByRole("heading", { name: "Members" })).toBeVisible({
    timeout: 15_000,
  })
  await expect(
    tab.getByRole("cell", { name: USER_EMAIL, exact: true }).first()
  ).toBeVisible()
})

Then("the first tab has member management controls", async ({ page }) => {
  await expect(page.getByRole("button", { name: "Add member" })).toBeVisible({
    timeout: 15_000,
  })
})

Then("the first tab's draft field is empty", async ({ page }) => {
  await expect(page.getByLabel("Account email")).toHaveValue("")
})

Then("the first tab has no member management controls", async ({ page }) => {
  await expect(page.getByRole("form", { name: "Add member" })).toBeHidden({ timeout: 15_000 })
})

Then("the second tab still has member management controls", async ({ page: _page }) => {
  await expect(secondTab().getByRole("button", { name: "Add member" })).toBeVisible({ timeout: 15_000 })
})

Then("the second tab's draft still contains {string}", async ({ page: _page }, value: string) => {
  await expect(secondTab().getByLabel("Account email")).toHaveValue(value)
})

Then("I see {string}", async ({ page }, text: string) => {
  await expect(page.getByText(text, { exact: false }).first()).toBeVisible({ timeout: 15_000 })
})

Then("I do not see {string}", async ({ page }, text: string) => {
  await expect(page.getByText(text, { exact: false }).first()).toBeHidden()
})

Then("I see the heading {string}", async ({ page }, text: string) => {
  await expect(page.getByRole("heading", { name: text }).first()).toBeVisible({
    timeout: 15_000,
  })
})

When("I fill {string} with {string}", async ({ page }, label: string, value: string) => {
  await page.getByLabel(label).fill(value)
})

Then("the create project form is absent", async ({ page }) => {
  // Without system project creation permission there is no form at all.
  await expect(page.getByRole("button", { name: "Create project" })).toHaveCount(0)
  await expect(page.getByLabel("Project name")).toHaveCount(0)
})

When("I submit the create project form", async ({ page }) => {
  await page.getByRole("button", { name: "Create project" }).click()
})

Then("the heading {string} is absent", async ({ page }, text: string) => {
  await expect(page.getByRole("heading", { name: text })).toBeHidden()
})
