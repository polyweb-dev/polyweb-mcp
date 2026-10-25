import { expect } from "@playwright/test"
import type { Page } from "@playwright/test"
import { Given, Then, When } from "./fixtures"
import { installBackendStub } from "./backendStub"
import {
  clearProjectStubMemberships,
  holdProjectStubMembers,
  installProjectStub,
  releaseProjectStubMembers,
  resetProjectStub,
  setProjectStubRoles,
  setProjectStubAccount,
} from "./projectStub"

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
    return json(route, {
      id: "33333333-3333-4333-8333-333333333333",
      email: USER_EMAIL,
      role: "agent",
      is_active: true,
      is_superuser: false,
      is_verified: true,
    })
  })
}

async function installAll(page: Page, systemPermissions: string[] = []): Promise<void> {
  resetProjectStub()
  setProjectStubAccount(USER_EMAIL, systemPermissions)
  await installBackendStub(page)
  await installProjectStub(page)
  await installProjectAuth(page)
}

let secondPage: Page | null = null

Given("the projects backend is stubbed", async ({ page }) => {
  await installAll(page)
})

Given("the projects backend is stubbed for a system administrator", async ({ page }) => {
  await installAll(page, ["project.create"])
})

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
  secondPage = await context.newPage()
  await installBackendStub(secondPage)
  await installProjectStub(secondPage)
  await installProjectAuth(secondPage)
  await secondPage.goto(path)
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
  if (secondPage === null) throw new Error("second tab not open")
  await secondPage.evaluate(() => window.dispatchEvent(new Event("focus")))
})

When("I type {string} into the field {string} of the second tab", async ({ page: _page }, value: string, label: string) => {
  if (secondPage === null) throw new Error("second tab not open")
  await secondPage.getByLabel(label).fill(value)
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
  if (secondPage === null) throw new Error("second tab not open")
  await expect(secondPage.getByRole("heading", { name: "Members" })).toBeVisible({
    timeout: 15_000,
  })
  await expect(
    secondPage.getByRole("cell", { name: USER_EMAIL, exact: true }).first()
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
  if (secondPage === null) throw new Error("second tab not open")
  await expect(secondPage.getByRole("button", { name: "Add member" })).toBeVisible({ timeout: 15_000 })
})

Then("the second tab's draft still contains {string}", async ({ page: _page }, value: string) => {
  if (secondPage === null) throw new Error("second tab not open")
  await expect(secondPage.getByLabel("Account email")).toHaveValue(value)
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

When("I submit the create project form", async ({ page }) => {
  await page.getByRole("button", { name: "Create project" }).click()
})

Then("the heading {string} is absent", async ({ page }, text: string) => {
  await expect(page.getByRole("heading", { name: text })).toBeHidden()
})
