import { expect } from "@playwright/test"
import { Given, When, Then } from "./fixtures"
import { providerQuotaSurface } from "./providerQuotaUi"
import { setStubbedCrdTotals, setStubbedProviderLimits } from "./backendStub"
import { userAccountBody } from "./accountStub"

/**
 * Keenable card shared bar (@keenable-cr1).
 *
 * All backend traffic is stubbed. The local keenableCreditLimits fixture
 * mirrors the canonical card fixtures: null keyless budget and pool, keyed
 * monthly allowance of 100000 native units at the current price, decimal
 * request text with authoritative rate confidence on the keyless rail, and
 * supported search and fetch records with null keyless cost metadata.
 * Assertions use roles, labels, rectangles, and computed colors only.
 */

function multiplyByFour(amount: string): string {
  const dot = amount.indexOf(".")
  if (dot === -1) return (BigInt(amount) * 4n).toString()
  const scale = amount.length - dot - 1
  const digits = amount.slice(0, dot) + amount.slice(dot + 1)
  const product = BigInt(digits === "" ? "0" : digits) * 4n
  const text = product.toString().padStart(scale + 1, "0")
  const head = text.slice(0, text.length - scale)
  const tail = text.slice(text.length - scale).replace(/0+$/, "")
  return tail === "" ? head : head + "." + tail
}

function keenableConversionProfile(): Record<string, unknown> {
  return {
    reference_usd_per_crd: "0.001",
    native_usd_per_unit: "0.004",
    cost_basis: "priced_native_use",
    price_version: "list_price",
    source: "list_price_assumed",
    estimated: true,
  }
}

function keenableKeylessConversionProfile(): Record<string, unknown> {
  return {
    reference_usd_per_crd: "0.001",
    native_usd_per_unit: "0",
    cost_basis: "priced_native_use",
    price_version: "",
    source: "unbilled_keyless",
    estimated: false,
  }
}

function keenableRecord(
  operation: string,
  authMode: string,
  profile: Record<string, unknown>,
): Record<string, unknown> {
  return {
    provider: "keenable",
    operation,
    auth_mode: authMode,
    supported: true,
    transport_available: true,
    native_pool_id: authMode === "keyed" ? "keenable:keyed:request" : null,
    rate: null,
    budget: null,
    conversion_profile: profile,
    plan_name: authMode === "keyed" ? "Monthly free requests" : "Keyless public pool",
    usage_url: authMode === "keyed" ? "https://app.keenable.ai/console" : null,
    version: 1,
  }
}

function keenableCreditLimits(
  authMode: "keyed" | "keyless",
  remaining: string,
): unknown[] {
  if (authMode === "keyed") {
    const remainingCrd = multiplyByFour(remaining)
    const view = (operation: string): Record<string, unknown> => ({
      state: "finite",
      operation,
      remaining_crd: remainingCrd,
      local_remaining_crd: null,
      request_cost_crd: "4",
      shared_pool_id: "keenable:keyed:request",
      possible_standard_calls: remaining,
      price_version: "list_price",
      priced: true,
    })
    return [
      {
        provider: "keenable",
        active_auth_mode: "keyed",
        auths: [
          {
            auth_mode: "keyed",
            transport_available: true,
            search: keenableRecord("search", "keyed", keenableConversionProfile()),
            fetch: keenableRecord("fetch", "keyed", keenableConversionProfile()),
            free_tiers: [],
            paid_tiers: [],
            unknown_tiers: [],
            tier_split_known: true,
            aggregate_pool: {
              pool_id: "keenable:keyed:request",
              provider: "keenable",
              auth_mode: "keyed",
              native_unit: "REQUEST",
              remaining,
              allowance: "100000",
              actual_spend_usd: null,
              source: "local_ledger",
              confidence: "estimated",
              reset_at: "2026-11-01T00:00:00Z",
              observed_at: "2026-03-10T12:00:00Z",
              version: 1,
              credential_generation: 7,
              next_sync_at: null,
              stale: false,
              manual_anchor: false,
            },
            crd_views: [view("search"), view("fetch")],
            rate_progress: [],
            grants: null,
            detail: null,
          },
        ],
        documented_keyless_operations: ["search", "fetch"],
        version: 1,
        generated_at: "2026-03-10T12:00:00Z",
      },
    ]
  }
  const progress = (operation: string): Record<string, unknown> => ({
    bucket_id: "keenable:keyless:requests",
    operation,
    window: "1h",
    unit: "requests",
    remaining,
    limit: "1000",
    reset_at: null,
    source: "documented_keyless",
    confidence: "authoritative",
    kind: "rate",
    stale: false,
    enforceable: true,
  })
  const unmetered = (operation: string): Record<string, unknown> => ({
    state: "unmetered",
    operation,
    remaining_crd: null,
    local_remaining_crd: null,
    request_cost_crd: null,
    shared_pool_id: null,
    possible_standard_calls: null,
    price_version: null,
    priced: false,
  })
  return [
    {
      provider: "keenable",
      active_auth_mode: "keyless",
      auths: [
        {
          auth_mode: "keyless",
          transport_available: true,
          search: keenableRecord("search", "keyless", keenableKeylessConversionProfile()),
          fetch: keenableRecord("fetch", "keyless", keenableKeylessConversionProfile()),
          free_tiers: [],
          paid_tiers: [],
          unknown_tiers: [],
          tier_split_known: true,
          aggregate_pool: null,
          crd_views: [unmetered("search"), unmetered("fetch")],
          rate_progress: [progress("search"), progress("fetch")],
          grants: null,
          detail: {
            plan_name: "Keyless public pool",
            native_unit: null,
            native_balance: null,
            native_allowance: null,
            usd_per_call: null,
            actual_spend_usd: null,
            reset_at: null,
            reset_rule: "unknown",
            usage_url: null,
            source: "documented_keyless",
            confidence: "observed",
            last_sync_at: null,
            stale: false,
            price_version: "",
            crd_split_note: null,
            rate_windows: [
              {
                bucket_id: "keenable:keyless:requests",
                limit: "10",
                window: "1s",
                scope: "ip",
                unit: "requests",
                remaining: null,
                reset_at: null,
                source: "documented_keyless",
                confidence: "observed",
              },
              {
                bucket_id: "keenable:keyless:requests",
                limit: "1000",
                window: "1h",
                scope: "ip",
                unit: "requests",
                remaining: null,
                reset_at: null,
                source: "documented_keyless",
                confidence: "observed",
              },
            ],
            tier_split_known: true,
            aggregate_pool_id: null,
          },
        },
      ],
      documented_keyless_operations: ["search", "fetch"],
      version: 1,
      generated_at: "2026-03-10T12:00:00Z",
    },
  ]
}

const BAR_COLOR_RGB: Record<string, string> = {
  green: "rgb(34, 197, 94)",
  yellow: "rgb(234, 179, 8)",
  orange: "oklch(0.705 0.213 47.604)",
  red: "rgb(239, 68, 68)",
}

Given(
  "the Keenable card fixture uses {string} access with {string} capacity",
  async ({ page }, access: string, capacity: string) => {
    if (access !== "keyed" && access !== "keyless") {
      throw new Error(`Unknown Keenable access: ${access}`)
    }
    await page.unroute("**/auth/jwt/refresh").catch(() => {})
    await page.unroute("**/users/me").catch(() => {})
    await page.route("**/auth/jwt/refresh", (route) => {
      if (route.request().method() !== "POST") return route.fallback()
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          access_token: "stub-access-token",
          token_type: "bearer",
          expires_in: 900,
          refresh_expires_in: 604800,
        }),
      })
    })
    await page.route("**/users/me", (route) => {
      if (route.request().method() !== "GET") return route.fallback()
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        // Role-less account; the Before hook's system access serves the
        // system administrator permission set.
        body: JSON.stringify(
          userAccountBody("11111111-1111-4111-8111-111111111111", "admin@example.com", {
            username: "admin",
          })
        ),
      })
    })
    setStubbedProviderLimits(keenableCreditLimits(access, capacity))
    setStubbedCrdTotals([])
  },
)

When("I open the Keenable quota details", async ({ page }) => {
  await page
    .getByRole("button", { name: /Credit details for Keenable/i })
    .click()
  await expect(page.getByText("Quota details")).toBeVisible()
})

When("I cancel the Keenable details", async ({ page }) => {
  await page.keyboard.press("Escape")
})

Then(
  "the Keenable {string} bar shows {string} percent with {string} color",
  async ({ page }, kind: string, percent: string, color: string) => {
    let bar
    if (kind === "funds") {
      bar = page.getByRole("progressbar", {
        name: "Keenable credit units remaining",
      })
    } else if (kind === "search") {
      bar = page.getByRole("progressbar", {
        name: "Keenable search and fetch limits remaining",
      })
    } else if (kind === "fetch") {
      bar = page.getByRole("progressbar", {
        name: "Keenable search and fetch limits remaining",
      })
    } else if (kind === "rate") {
      bar = page
        .getByRole("progressbar", { name: /Keenable search and fetch limits remaining/i })
        .first()
    } else {
      throw new Error(`Unknown Keenable bar kind: ${kind}`)
    }
    await expect(bar).toBeVisible()
    await expect(bar).toHaveAttribute("aria-valuenow", percent)
    const expected = BAR_COLOR_RGB[color]
    if (expected === undefined) throw new Error(`Unknown bar color: ${color}`)
    const inner = bar.locator("div").first()
    const background = await inner.evaluate(
      (element) => getComputedStyle(element).backgroundColor,
    )
    expect(background).toBe(expected)
  },
)

Then("the Keenable rate bar occupies a line below its text", async ({ page }) => {
  const text = page.getByText("Search and fetch limits", { exact: true })
  const bar = page
    .getByRole("progressbar", {
      name: "Keenable search and fetch limits remaining",
    })
    .first()
  await expect(text).toBeVisible()
  await expect(bar).toBeVisible()
  const textBox = await text.boundingBox()
  const barBox = await bar.boundingBox()
  expect(textBox).not.toBeNull()
  expect(barBox).not.toBeNull()
  if (textBox === null || barBox === null) throw new Error("Missing rectangles")
  expect(barBox.y).toBeGreaterThanOrEqual(textBox.y + textBox.height - 2)
})

Then("the Keenable request counts contain no decimal part", async ({ page }) => {
  await expect(page.getByText("1,000 of 1,000 requests left this hour", { exact: true })).toBeVisible()
  await expect(page.getByText("1000.00000000")).toHaveCount(0)
})

Then("the Keenable keyless costs are struck beside Free", async ({ page }) => {
  const popover = page.locator('[data-slot="popover-content"]')
  await expect(popover.locator("s")).toHaveCount(2)
  await expect(popover.getByText("Free", { exact: true }).first()).toBeVisible()
})

Then("the Keenable keyless details contain no authoritative label", async ({ page }) => {
  await expect(page.getByText("authoritative")).toHaveCount(0)
})

Then("the Keenable details should show {string}", async ({ page }, text: string) => {
  await expect(page.getByText(text, { exact: false }).first()).toBeVisible()
})

Then("the Keenable card should show the {string} action", async ({ page }, label: string) => {
  const card = providerQuotaSurface(page, "Keenable")
  const direct = card.getByRole("button", { name: new RegExp(label, "i") })
  if ((await direct.count()) > 0) {
    await expect(direct.first()).toBeVisible()
    return
  }
  // Dialog actions live in the card `…` menu.
  await card.getByRole("button", { name: /^Actions for /i }).click()
  await expect(page.getByRole("button", { name: label, exact: true })).toBeVisible()
  await page.keyboard.press("Escape")
})

Then("the Keenable card should show no funds bar", async ({ page }) => {
  const card = providerQuotaSurface(page, "Keenable")
  await expect(
    card.getByRole("progressbar", { name: "Keenable credit units remaining" }),
  ).toHaveCount(0)
})

Then("the Keenable details control regains focus", async ({ page }) => {
  await expect(
    page.getByRole("button", { name: /Credit details for Keenable/i }),
  ).toBeFocused()
})

Then("the Keenable card should offer no Refresh action", async ({ page }) => {
  const surface = providerQuotaSurface(page, "Keenable")
  await expect(surface).toBeVisible()
  await expect(surface.getByRole("button", { name: /Refresh/i })).toHaveCount(0)
})
