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
  "Sign-in is not ready yet. Set FREESEARCH_AUTH_JWT_SECRET on the server, then restart the API."

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
const provisioningBodies: unknown[] = []

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

Then("the auth screen shows the FreeSearch brand", async ({ page }) => {
  await expect(page.getByText("FreeSearch", { exact: true })).toBeVisible()
  const logo = page.locator('img[src*="freesearch"]')
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

/** The request body is exactly {email, password}: no role and no extra field. */
function expectEmailAndPasswordOnly(body: unknown, email: string): void {
  expect(body).not.toBeNull()
  expect(typeof body).toBe("object")
  const record = body as Record<string, unknown>
  expect(Object.keys(record).sort()).toEqual(["email", "password"])
  expect(record.email).toBe(email)
  expect(typeof record.password).toBe("string")
}

Then("the register screen offers no account-type choice", async ({ page }) => {
  await expectNoAccountTypeChoice(page.locator("form"))
})

Then("the registration request carried only email and password", async () => {
  expect(registrationBodies).toHaveLength(1)
  expectEmailAndPasswordOnly(registrationBodies[0], "weak-rule@example.com")
})

const PROVISIONED_EMAIL = "new-teammate@example.com"

Given("the account provisioning backend accepts new accounts", async ({ page }) => {
  provisioningBodies.length = 0
  await page.route(
    (url) => url.pathname === "/api/v1/users",
    (route) => {
      if (route.request().method() !== "POST") return route.fallback()
      const body = parsedBody(route)
      provisioningBodies.push(body)
      const email =
        body !== null && typeof body === "object" && typeof (body as { email?: unknown }).email === "string"
          ? (body as { email: string }).email
          : PROVISIONED_EMAIL
      return json(
        route,
        {
          id: "55555555-5555-4555-8555-555555555555",
          email,
          auth_provider: "local",
          auth_provider_id: null,
          username: null,
          first_name: null,
          last_name: null,
          is_active: true,
          is_verified: false,
        },
        201
      )
    }
  )
})

When("I open the account administration screen", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto("/admin/users")
  await expect(page.getByRole("heading", { name: "Accounts", exact: true })).toBeVisible({
    timeout: 15_000,
  })
  await expect(page.getByRole("button", { name: "Create account", exact: true })).toBeVisible()
})

Then("the account administration screen offers no account-type choice", async ({ page }) => {
  await expectNoAccountTypeChoice(page.locator("main form"))
})

When("I create the account from the administration screen", async ({ page }) => {
  const main = page.locator("main")
  await main.getByLabel("Email", { exact: true }).fill(PROVISIONED_EMAIL)
  // Test-only placeholder that satisfies the password rule; not a real secret.
  await main.getByLabel("Password", { exact: true }).fill("Stub-Only-Passw0rd!")
  await main.getByLabel("Confirm password", { exact: true }).fill("Stub-Only-Passw0rd!")
  await main.getByRole("button", { name: "Create account", exact: true }).click()
})

Then("the account provisioning request carried only email and password", async () => {
  await expect.poll(() => provisioningBodies.length).toBe(1)
  expectEmailAndPasswordOnly(provisioningBodies[0], PROVISIONED_EMAIL)
})

Then("the administration receipt names the account without a role", async ({ page }) => {
  const receipt = page.getByRole("status").filter({ hasText: PROVISIONED_EMAIL })
  await expect(receipt).toBeVisible()
  expect((await receipt.textContent()) ?? "").not.toMatch(/\b(Admin|Developer|Agent|role)\b/i)
})
