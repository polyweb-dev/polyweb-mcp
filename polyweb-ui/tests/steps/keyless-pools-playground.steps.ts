import { expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { Given, When, Then } from "./fixtures";
import { projectStubId } from "./projectStub";

/**
 * TASK-000065 regression steps (test-only, no production changes).
 *
 * Real UI contracts reused from the mapped source:
 * - Register: heading "Create an account", labels Email/Username/First name/
 *   Last name/Password/Confirm password, button "Create account".
 * - Login: heading "Sign in", button "Sign in".
 * - Projects: label "Project name", button "Create project".
 * - Playground: placeholder "Search the web", button "Search" (exact),
 *   spinbutton "Number of results", no-pool copy
 *   "No provider is set up for this project." plus link "Set up providers".
 * - Keys and pools: heading "Keys and pools", buttons "Add key"/"Create pool",
 *   pool row menu trigger `Actions for <label>` with items "Edit pool",
 *   "Copy to another project", "Remove from project"/"Assign to project",
 *   "Delete pool".
 *
 * ANTICIPATED (deliberately missing) UI contracts these scenarios pin down:
 * - Keyless key creation offers an Authentication choice that includes a
 *   no-secret keyless mode, so a Keenable keyless pool needs no API key.
 * - A one-shot "Bulk create pools" control creates pools for several
 *   providers without per-key round trips and without vendor calls.
 * - A "Create keyless defaults" control provisions the supported keyless
 *   free-tier default pools without API keys and without vendor calls.
 * - Every pool menu item carries its own icon (svg) next to its label.
 * Until production implements them, the corresponding steps fail naturally
 * against the current source (missing control / missing icon / API 4xx).
 */

// ---------------------------------------------------------------------------
// Fresh-signup state (@live only; never exercised while authoring).
// ---------------------------------------------------------------------------

let freshProjectName = "";
let freshAccountEmail = "";

const FRESH_PASSWORD = "Str0ng-Passw0rd!2026";

function uniqueSuffix(): string {
  return `${Date.now().toString(36)}${Math.floor(Math.random() * 1e6).toString(36)}`;
}

async function registerFreshAccount(page: Page): Promise<void> {
  const suffix = uniqueSuffix();
  freshAccountEmail = `keyless-${suffix}@example.com`;
  const username = `keyless-${suffix}`.slice(0, 32);
  await page.goto("/register");
  await expect(page.getByRole("heading", { name: "Create an account" })).toBeVisible({ timeout: 15_000 });
  await page.getByLabel("Email").fill(freshAccountEmail);
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("First name").fill("Keyless");
  await page.getByLabel("Last name").fill("Probe");
  await page.getByLabel("Password", { exact: true }).fill(FRESH_PASSWORD);
  await page.getByLabel("Confirm password").fill(FRESH_PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
}

async function loginFreshAccount(page: Page): Promise<void> {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible({ timeout: 15_000 });
  await page.getByLabel("Email").fill(freshAccountEmail);
  await page.getByLabel("Password").fill(FRESH_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
}

async function createFreshProject(page: Page): Promise<void> {
  freshProjectName = `Keyless Probe ${uniqueSuffix()}`;
  await page.goto("/projects");
  await expect(page.getByRole("heading", { name: "Projects", exact: true })).toBeVisible({ timeout: 15_000 });
  await page.getByLabel("Project name").fill(freshProjectName);
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByRole("heading", { name: freshProjectName })).toBeVisible({ timeout: 15_000 });
}

async function selectFreshProject(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Select project" }).first().click();
  await page.getByRole("menuitem", { name: freshProjectName, exact: false }).first().click();
  await expect(page).toHaveURL(/\/p\/[0-9a-f-]{36}/, { timeout: 15_000 });
}

Given("a fresh signup with a new project with no provider pool", async ({ page }) => {
  await registerFreshAccount(page);
  await loginFreshAccount(page);
  await createFreshProject(page);
  await selectFreshProject(page);
});

Given("a fresh signup with a new project", async ({ page }) => {
  await registerFreshAccount(page);
  await loginFreshAccount(page);
  await createFreshProject(page);
  await selectFreshProject(page);
});

// ---------------------------------------------------------------------------
// No-pool guidance (@live scenario A).
// ---------------------------------------------------------------------------

Then("the playground should show the no-pool setup guidance with a link to set up providers", async ({ page }) => {
  const main = page.locator("main");
  await expect(main.getByText("No provider is set up for this project.", { exact: false }).first()).toBeVisible({ timeout: 15_000 });
  const setupLink = main.getByRole("link", { name: "Set up providers" });
  await expect(setupLink).toBeVisible({ timeout: 15_000 });
  await expect(setupLink).toHaveAttribute("href", /\/providers$/);
});

Then("the no-pool error should not present as a timeout", async ({ page }) => {
  await expect(page.locator("main")).not.toContainText(/timed out|timeout/i);
});

// ---------------------------------------------------------------------------
// Keyless pool creation + Full trace detail (@live scenario B).
// ---------------------------------------------------------------------------

When("I create a keyless pool for Keenable without an API key and assign it to the new project", async ({ page }) => {
  await page.goto("/account");
  await page.getByRole("tab", { name: "Keys and pools", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Keys and pools" })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Add key", exact: true }).first().click();
  const dialog = page.getByRole("dialog", { name: "Add key" });
  await expect(dialog).toBeVisible({ timeout: 15_000 });
  // Anticipated keyless contract: the Authentication select offers a
  // no-secret keyless mode. Current source only offers API key/OAuth, so
  // this fails naturally until keyless creation exists.
  const authSelect = dialog.getByLabel("Authentication", { exact: true });
  await authSelect.click();
  await page.getByRole("option", { name: /Keyless/i }).click();
  await dialog.getByLabel("Label", { exact: true }).fill(`Keenable keyless ${uniqueSuffix()}`);
  await expect(dialog.getByLabel("API key", { exact: true })).toHaveCount(0);
  await dialog.getByRole("button", { name: "Save key", exact: true }).click();
  await expect(dialog).toBeHidden({ timeout: 15_000 });
  // Assign the new keyless pool to the fresh project via the row Create pool
  // action; the pool name is not known, so use the first matching row.
  const row = page.getByRole("row").filter({ hasText: /Keenable/ }).first();
  await row.getByRole("button", { name: "Create pool" }).click();
  const poolDialog = page.getByRole("dialog", { name: "Create pool" });
  await expect(poolDialog).toBeVisible({ timeout: 15_000 });
  await poolDialog.getByLabel("Pool name").fill(`Keenable keyless ${uniqueSuffix()}`);
  await poolDialog.getByRole("button", { name: "Create pool", exact: true }).click();
  await expect(poolDialog).toBeHidden({ timeout: 15_000 });
});

When("I open the Full trace detail of the successful search", async ({ page }) => {
  const table = page.getByRole("table");
  await expect(table).toBeVisible({ timeout: 15_000 });
  await table.getByRole("button", { name: "View details", exact: true }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible({ timeout: 15_000 });
});

Then("the trace detail should show the recorded results", async ({ page }) => {
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible({ timeout: 15_000 });
  // Full trace policy stores the search output; the detail must hold results,
  // not the stored-but-empty copy ("No result was returned" / "Snippet not
  // recorded" alone would mean results were not stored).
  await expect(dialog.getByText(/% match/i).first()).toBeVisible({ timeout: 15_000 });
});

// ---------------------------------------------------------------------------
// Bulk + default pool creation (stubbed, no provider calls).
// ---------------------------------------------------------------------------

const vendorRequests: string[] = [];
let vendorWatchInstalled: object | null = null;

function watchVendorRequests(page: Page): void {
  if (vendorWatchInstalled === page) return;
  vendorWatchInstalled = page;
  vendorRequests.length = 0;
  page.on("request", (request) => {
    const url = request.url();
    if (/^https?:\/\//.test(url) && !/localhost|127\.0\.0\.1/.test(url)) vendorRequests.push(url);
  });
}

When("I bulk create pools for {string} for project Alpha without provider calls", async ({ page }, list: string) => {
  watchVendorRequests(page);
  const providers = list.split(",").map((entry) => entry.trim()).filter((entry) => entry !== "");
  expect(providers.length).toBeGreaterThan(1);
  await page.goto("/account");
  await page.getByRole("tab", { name: "Keys and pools", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Keys and pools" })).toBeVisible({ timeout: 15_000 });
  // Anticipated bulk contract: one dialog creates pools for several
  // providers at once. Fails naturally while only per-key Create pool exists.
  await page.getByRole("button", { name: /Bulk create pools/i }).click();
  const dialog = page.getByRole("dialog", { name: /Bulk create pools/i });
  await expect(dialog).toBeVisible({ timeout: 10_000 });
  for (const provider of providers) {
    await dialog.getByRole("checkbox", { name: provider, exact: false }).check();
  }
  await dialog.getByRole("button", { name: /Create pools/i }).click();
  await expect(dialog).toBeHidden({ timeout: 15_000 });
});

Then("project Alpha should have pools for {string}", async ({ page }, list: string) => {
  const providers = list.split(",").map((entry) => entry.trim()).filter((entry) => entry !== "");
  await page.goto(`/p/${projectStubId("Alpha")}/providers`);
  await expect(page.getByRole("heading", { name: "Providers" })).toBeVisible({ timeout: 15_000 });
  for (const provider of providers) {
    await expect(page.locator("main").getByText(provider, { exact: false }).first()).toBeVisible({ timeout: 15_000 });
  }
});

Then("no vendor request should have been made", async () => {
  expect(vendorRequests).toEqual([]);
});

When("I create the keyless free-tier default pools for project Alpha without an API key", async ({ page }) => {
  watchVendorRequests(page);
  await page.goto("/account");
  await page.getByRole("tab", { name: "Keys and pools", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Keys and pools" })).toBeVisible({ timeout: 15_000 });
  // Anticipated defaults contract: one control provisions the supported
  // keyless free-tier pools with no secret. Fails naturally while missing.
  await page.getByRole("button", { name: /Create keyless defaults/i }).click();
  const dialog = page.getByRole("dialog", { name: /Keyless defaults|Default pools/i });
  await expect(dialog).toBeVisible({ timeout: 10_000 });
  await dialog.getByRole("button", { name: /Create|Save/i }).click();
  await expect(dialog).toBeHidden({ timeout: 15_000 });
});

Then("project Alpha should have a keyless pool for Keenable without an API key", async ({ page }) => {
  await page.goto(`/p/${projectStubId("Alpha")}/providers`);
  const row = page.getByRole("row").filter({ hasText: /Keenable/ }).first();
  await expect(row).toBeVisible({ timeout: 15_000 });
  await expect(row).toContainText(/No key needed/i);
});

// ---------------------------------------------------------------------------
// Pool menu icon consistency (stubbed, no provider calls).
// ---------------------------------------------------------------------------

When("I open the pool actions menu for {string}", async ({ page }, pool: string) => {
  watchVendorRequests(page);
  await expect(page.getByRole("button", { name: `Actions for ${pool}` })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: `Actions for ${pool}` }).click();
  await expect(page.getByRole("menu").first()).toBeVisible({ timeout: 10_000 });
});

Then("the pool actions menu should show Edit pool, Copy to another project, Remove from project and Delete pool each with an icon", async ({ page }) => {
  const menu = page.getByRole("menu").first();
  await expect(menu).toBeVisible({ timeout: 10_000 });
  for (const label of ["Edit pool", "Copy to another project", "Remove from project", "Delete pool"]) {
    const item = menu.getByRole("menuitem", { name: label });
    await expect(item).toBeVisible({ timeout: 10_000 });
    // Consistency contract: every popup/menu action pairs its label with an
    // icon. Current RowActionsMenu renders bare labels, so this fails
    // naturally until icons are added.
    await expect(item.locator("svg").first()).toBeVisible({ timeout: 5_000 });
  }
});
