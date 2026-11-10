import { expect } from "@playwright/test"
import { Given, When, Then } from "./fixtures"

/**
 * Auth display acceptance for Turn 5.
 *
 * The three user-directed fixes: friendly auth error text, repository brand
 * on the account screens, and the friendly configuration state. All backend
 * traffic in these scenarios is stubbed, so the real backend is never
 * touched and no account is created.
 */

const PASSWORD_RULE =
  "Use 12 to 128 characters with an upper-case letter, a lower-case letter, a digit, and a symbol."
const BAD_CREDENTIALS = "The email address or the password is not correct."
const CONFIG_STATE =
  "Sign-in is not ready yet. Set POLYWEB_AUTH_JWT_SECRET on the server, then restart the API."

async function json(
  route: import("@playwright/test").Route,
  body: unknown,
  status = 200
): Promise<void> {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  })
}

Given("the auth bootstrap reports an anonymous session", async ({ page }) => {
  await page.route("**/auth/jwt/refresh", (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    return json(route, { detail: "invalid refresh credential" }, 401)
  })
  await page.route("**/users/me", (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    return json(route, { detail: "not authenticated" }, 401)
  })
})

/** Parsed bodies of the account-creation requests the UI sent (per scenario). */
const registrationBodies: unknown[] = []

function parsedBody(route: import("@playwright/test").Route): unknown {
  const raw = route.request().postData()
  try {
    return raw === null ? null : (JSON.parse(raw) as unknown)
  } catch {
    return raw
  }
}

Given("the auth backend rejects registration with the password rule", async ({ page }) => {
  registrationBodies.length = 0
  await page.route("**/auth/register", (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    registrationBodies.push(parsedBody(route))
    return json(
      route,
      {
        detail: {
          code: "REGISTER_INVALID_PASSWORD",
          reason: "Password should contain at least one digit and one symbol.",
        },
      },
      400
    )
  })
})

Given("the auth backend rejects login with bad credentials", async ({ page }) => {
  await page.route("**/auth/jwt/login", (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    return json(route, { detail: "LOGIN_BAD_CREDENTIALS" }, 400)
  })
})

Given("the auth backend reports an unconfigured secret on login", async ({ page }) => {
  await page.route("**/auth/jwt/login", (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    return json(route, { detail: "account authentication is not configured" }, 503)
  })
})

When("I open the login screen", async ({ page }) => {
  await page.goto("/login")
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible()
})

When("I open the register screen", async ({ page }) => {
  await page.goto("/register")
  await expect(page.getByRole("heading", { name: "Create an account" })).toBeVisible()
})

When("I submit a registration with a weak password", async ({ page }) => {
  await page.getByLabel("Email").fill("weak-rule@example.com")
  await page.getByLabel("Username").fill("weak-rule-agent")
  await page.getByLabel("First name").fill("Ada")
  await page.getByLabel("Last name").fill("Lovelace")
  await page.getByLabel("Password", { exact: true }).fill("abcdefghijkl")
  await page.getByLabel("Confirm password").fill("abcdefghijkl")
  await page.getByRole("button", { name: "Create account" }).click()
})

When("I submit a login with any credentials", async ({ page }) => {
  await page.getByLabel("Email").fill("ada@example.com")
  await page.getByLabel("Password").fill("correct-horse-battery-99")
  await page.getByRole("button", { name: "Sign in" }).click()
})

Then("the register screen shows the password rule text", async ({ page }) => {
  await expect(page.getByRole("alert")).toHaveText(PASSWORD_RULE)
})

Then("the register screen shows no raw JSON body", async ({ page }) => {
  const alert = page.getByRole("alert")
  await expect(alert).toBeVisible()
  await expect(alert).not.toContainText("REGISTER_INVALID_PASSWORD")
  await expect(alert).not.toContainText("{")
  await expect(alert).not.toContainText("reason")
})

Then("the login screen shows the bad-credentials text", async ({ page }) => {
  await expect(page.getByRole("alert")).toHaveText(BAD_CREDENTIALS)
})

Then("the login screen shows no raw JSON body", async ({ page }) => {
  const alert = page.getByRole("alert")
  await expect(alert).toBeVisible()
  await expect(alert).not.toContainText("LOGIN_BAD_CREDENTIALS")
  await expect(alert).not.toContainText("{")
})

Then("the auth screen shows the Polyweb brand", async ({ page }) => {
  await expect(page.getByText("Polyweb", { exact: true })).toBeVisible()
  const logo = page.locator('img[src*="polyweb"]')
  await expect(logo).toHaveCount(1)
  await expect(logo).toHaveAttribute("alt", "")
})

Then("the auth screen shows exactly one page title", async ({ page }) => {
  await expect(page.getByRole("heading")).toHaveCount(1)
})

Then("the login screen shows the configuration state text", async ({ page }) => {
  await expect(page.getByRole("alert")).toHaveText(CONFIG_STATE)
})

/**
 * No account-type choice: no radio, select, listbox or role wording inside the
 * page content. Authority comes from project and system role assignments,
 * never from the account itself.
 */
async function expectNoAccountTypeChoice(scope: import("@playwright/test").Locator): Promise<void> {
  await expect(scope.getByRole("radio")).toHaveCount(0)
  await expect(scope.getByRole("combobox")).toHaveCount(0)
  await expect(scope.getByRole("listbox")).toHaveCount(0)
  await expect(scope.getByText(/\b(role|account type)\b/i)).toHaveCount(0)
}

/**
 * The public registration payload: email, password, username, first name,
 * and last name only. No role, account type, or confirmation field, and no
 * privilege or account-type keys.
 */
function expectPublicRegistrationPayload(body: unknown, email: string): void {
  expect(body).not.toBeNull()
  expect(typeof body).toBe("object")
  const record = body as Record<string, unknown>
  expect(Object.keys(record).sort()).toEqual([
    "email",
    "first_name",
    "last_name",
    "password",
    "username",
  ])
  expect(record.email).toBe(email)
  expect(typeof record.password).toBe("string")
  expect(typeof record.username).toBe("string")
  expect(typeof record.first_name).toBe("string")
  expect(typeof record.last_name).toBe("string")
}

Then("the register screen offers no account-type choice", async ({ page }) => {
  await expectNoAccountTypeChoice(page.locator("form"))
})

Then("the registration request carried the public registration payload", async () => {
  expect(registrationBodies).toHaveLength(1)
  expectPublicRegistrationPayload(registrationBodies[0], "weak-rule@example.com")
})
