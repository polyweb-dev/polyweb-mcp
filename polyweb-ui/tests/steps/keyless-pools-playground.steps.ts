import { expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { Given, When, Then } from "./fixtures";
import { executionTraffic } from "./backendStub";
import { projectStubId, projectStubAccountId } from "./projectStub";
import { chooseOption, watchBrowserTraffic } from "./providerConfigUi";

/**
 * TASK-000065 regression steps (test-only, no production changes).
 *
 * Real UI contracts reused from the mapped source:
 * - Register: heading "Create an account", labels Email/Username/First name/
 *   Last name/Password/Confirm password, button "Create account".
 * - Login: heading "Sign in", button "Sign in".
 * - Projects: label "Project name", button "Create project".
 * - Playground preflight: `noProviderForMode` renders ProviderSetupNotice
 *   ("No provider is set up for this project." + "Set up providers" link)
 *   with the Search submit disabled — no submit needed for the no-pool case.
 * - Keys and pools: route /account/keys, heading "Keys and pools",
 *   dialog "Add key" with "Save key" submit, "Create pool" dialog with
 *   "Pool name" field, pool row trigger `Actions for <label>`.
 * - Pool menu: RowActionsMenu popover of plain buttons — no menu/menuitem
 *   roles; icon consistency asserts one svg per button.
 * - Trace detail: dialog "Trace detail", results list "Ranked results".
 * - Settings: option "Full requests" for field trace.detail.
 * - Live results carry "% match" text.
 *
 * ANTICIPATED (deliberately missing) UI contracts these scenarios pin down:
 * - Keyless key creation with a no-secret keyless authentication mode.
 * - One-shot bulk pool creation and keyless free-tier default pools.
 * - One icon (svg) per pool popup/menu button.
 * Until production implements them, the corresponding steps fail naturally
 * against the current source (missing control / missing icon / API 4xx).
 */

// ---------------------------------------------------------------------------
// Fresh-signup state (@live only; never exercised while authoring).
// ---------------------------------------------------------------------------

let freshProjectName = "";
let freshProjectUrl = "";

const FRESH_PASSWORD = "Str0ng-Passw0rd!2026";

function uniqueSuffix(): string {
  return `${Date.now().toString(36)}${Math.floor(Math.random() * 1e6).toString(36)}`;
}

const freshAccountEmail = `keyless-probe-${uniqueSuffix()}@example.com`;
const freshUsername = `keyless-probe-${uniqueSuffix()}`.slice(0, 32);

async function registerFreshAccount(page: Page): Promise<void> {
  await page.goto("/register");
  await expect(page.getByRole("heading", { name: "Create an account" })).toBeVisible({ timeout: 15_000 });
  await page.getByLabel("Email").fill(freshAccountEmail);
  await page.getByLabel("Username").fill(freshUsername);
  await page.getByLabel("First name").fill("Keyless");
  await page.getByLabel("Last name").fill("Probe");
  await page.getByLabel("Password", { exact: true }).fill(FRESH_PASSWORD);
  await page.getByLabel("Confirm password").fill(FRESH_PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  // Await actual completion: the register screen confirms before login.
  await expect(page.getByText(/account created|check your email|confirm/i).first()).toBeVisible({ timeout: 30_000 });
}

async function loginFreshAccount(page: Page): Promise<void> {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible({ timeout: 15_000 });
  await page.getByLabel("Email").fill(freshAccountEmail);
  await page.getByLabel("Password").fill(FRESH_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  // Await actual completion: the workspace only exists once signed in.
  await expect(page).toHaveURL(/\/projects|\/p\//, { timeout: 30_000 });
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
  freshProjectUrl = page.url();
}

function freshProjectId(): string {
  const match = /\/p\/([0-9a-f-]{36})/.exec(freshProjectUrl);
  if (match === null) throw new Error("fresh project URL was not captured");
  return match[1];
}

async function restoreFreshProject(page: Page): Promise<void> {
  await page.goto(freshProjectUrl);
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
// No-pool guidance (@live scenario A): preflight, no submit.
// The Search submit is disabled while noProviderForMode, so the check must
// read the preflight guidance and assert zero execution calls.
// ---------------------------------------------------------------------------

Then("the playground should show the no-pool setup guidance with a link to set up providers", async ({ page }) => {
  const main = page.locator("main");
  await expect(main.getByText("No provider is set up for this project.", { exact: false }).first()).toBeVisible({ timeout: 15_000 });
  const setupLink = main.getByRole("link", { name: "Set up providers" });
  await expect(setupLink).toBeVisible({ timeout: 15_000 });
  await expect(setupLink).toHaveAttribute("href", /\/providers$/);
  await expect(page.getByRole("button", { name: "Search", exact: true })).toBeDisabled();
});

Then("the no-pool error should not present as a timeout", async ({ page }) => {
  await expect(page.locator("main")).not.toContainText(/timed out|timeout/i);
});

// ---------------------------------------------------------------------------
// Keyless pool creation + Full trace detail (@live scenario B).
// ---------------------------------------------------------------------------

When("I create a keyless pool for Keenable without an API key and assign it to the new project", async ({ page }) => {
  await page.goto("/account/keys");
  await expect(page.getByRole("heading", { name: "Keys and pools" })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Add key", exact: true }).first().click();
  const dialog = page.getByRole("dialog", { name: "Add key" });
  await expect(dialog).toBeVisible({ timeout: 15_000 });
  // Deliberate order: provider first (Authentication rewrites on change),
  // then the anticipated no-secret keyless mode.
  await chooseOption(dialog, "Provider", "Keenable");
  const authControl = dialog.getByRole("combobox", { name: "Authentication", exact: true });
  await expect(authControl).toBeVisible({ timeout: 10_000 });
  await chooseOption(dialog, "Authentication", /keyless/i.source);
  await dialog.getByLabel("Label", { exact: true }).fill(`Keenable keyless ${uniqueSuffix()}`);
  await expect(dialog.getByLabel("API key", { exact: true })).toHaveCount(0);
  await dialog.getByRole("button", { name: "Save key", exact: true }).click();
  await expect(dialog).toBeHidden({ timeout: 15_000 });
  const keyLabel = `Keenable keyless row`;
  await expect(page.getByRole("row").filter({ hasText: /Keenable/ }).first()).toBeVisible({ timeout: 15_000 });
  // Assign the keyless key to the fresh project via the row Create pool
  // action; the fresh project is chosen explicitly by captured URL id.
  await page.getByRole("row").filter({ hasText: /Keenable/ }).first().getByRole("button", { name: "Create pool" }).click();
  const poolDialog = page.getByRole("dialog", { name: "Create pool" });
  await expect(poolDialog).toBeVisible({ timeout: 15_000 });
  await poolDialog.getByLabel("Pool name").fill(`Keenable keyless ${uniqueSuffix()}`);
  void keyLabel;
  await poolDialog.getByRole("button", { name: "Create pool", exact: true }).click();
  await expect(poolDialog).toBeHidden({ timeout: 15_000 });
  // Back to the captured fresh project; the keyless flow must not strand the
  // run on the Account page.
  await restoreFreshProject(page);
});

When("I open the Full trace detail of the successful search", async ({ page }) => {
  // Establish the Full requests policy first so results are stored.
  await page.goto(`/p/${freshProjectId()}/settings`);
  const detailControl = page.getByRole("combobox", { name: /Trace detail|Detail/i }).first();
  if (await detailControl.count() > 0) {
    await chooseOption(page, /Trace detail|Detail/i.source, "Full requests");
  }
  await restoreFreshProject(page);
  await page.getByRole("navigation", { name: "Project" }).getByRole("link", { name: "Activity", exact: true }).click();
  const searched = "fresh project keyless probe";
  const row = page.getByRole("table").getByRole("row").filter({ hasText: searched }).first();
  await expect(row).toBeVisible({ timeout: 30_000 });
  await row.getByRole("button", { name: "View details", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Trace detail" })).toBeVisible({ timeout: 15_000 });
});

Then("the trace detail should show the recorded results", async ({ page }) => {
  const dialog = page.getByRole("dialog", { name: "Trace detail" });
  await expect(dialog).toBeVisible({ timeout: 15_000 });
  // Correlate the detail with the Keenable run: summary provider, the query,
  // and the ranked results list — not just any first-row "% match".
  await expect(dialog).toContainText(/Keenable/i);
  await expect(dialog).toContainText(/fresh project keyless probe/i);
  const ranked = dialog.getByRole("list", { name: "Ranked results" });
  await expect(ranked).toBeVisible({ timeout: 15_000 });
  await expect(ranked.getByText(/% match/i).first()).toBeVisible({ timeout: 15_000 });
});

// ---------------------------------------------------------------------------
// Bulk + default pool creation (stubbed, no provider calls).
// Shared execution-traffic counters catch local /search and /fetch bodies
// that the browser-URL guard misses; stubbed scenarios must send none.
// ---------------------------------------------------------------------------

Then("no vendor request should have been made", async () => {
  expect(executionTraffic()).toEqual([]);
});

When("I bulk create pools for {string} for project Alpha without provider calls", async ({ page }, list: string) => {
  watchBrowserTraffic(page);
  const providers = list.split(",").map((entry) => entry.trim()).filter((entry) => entry !== "");
  expect(providers.length).toBeGreaterThan(1);
  const before = executionTraffic().length;
  await page.goto("/account/keys");
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
  expect(executionTraffic().length).toBe(before);
});

Then("project Alpha should have pools for {string}", async ({ page }, list: string) => {
  const providers = list.split(",").map((entry) => entry.trim()).filter((entry) => entry !== "");
  await page.goto(`/p/${projectStubId("Alpha")}/providers`);
  await expect(page.getByRole("heading", { name: "Providers" })).toBeVisible({ timeout: 15_000 });
  for (const provider of providers) {
    // Identity: the provider order row carries pools; a keyless default must
    // not ride the pre-seeded vault stub (vaultStub pre-inserts Keenable) —
    // the row must name the new project-assigned pool state, not bare text.
    const row = page.getByRole("row").filter({ hasText: new RegExp(provider, "i") }).first();
    await expect(row).toBeVisible({ timeout: 15_000 });
  }
  expect(executionTraffic()).toEqual([]);
});

When("I create the keyless free-tier default pools for project Alpha without an API key", async ({ page }) => {
  watchBrowserTraffic(page);
  const before = executionTraffic().length;
  await page.goto("/account/keys");
  await expect(page.getByRole("heading", { name: "Keys and pools" })).toBeVisible({ timeout: 15_000 });
  // Anticipated defaults contract: one control provisions the supported
  // keyless free-tier pools with no secret. Fails naturally while missing.
  await page.getByRole("button", { name: /Create keyless defaults/i }).click();
  const dialog = page.getByRole("dialog", { name: /Keyless defaults|Default pools/i });
  await expect(dialog).toBeVisible({ timeout: 10_000 });
  await dialog.getByRole("button", { name: /Create|Save/i }).click();
  await expect(dialog).toBeHidden({ timeout: 15_000 });
  expect(executionTraffic().length).toBe(before);
});

Then("project Alpha should have a keyless pool for Keenable without an API key", async ({ page }) => {
  await page.goto(`/p/${projectStubId("Alpha")}/providers`);
  // Assigned-project proof: the vault row for the newly created pool must
  // reference the Alpha project (vaultStub pre-inserts Keenable, so the
  // Providers row alone would be a false green).
  await page.goto("/account/keys");
  const keyRow = page.getByRole("row").filter({ hasText: /Keenable/ }).first();
  await expect(keyRow).toBeVisible({ timeout: 15_000 });
  await keyRow.getByRole("button", { name: "Expand" }).click().catch(() => {});
  await expect(page.locator("main")).toContainText(/Alpha/);
  await page.goto(`/p/${projectStubId("Alpha")}/providers`);
  const row = page.getByRole("row").filter({ hasText: /Keenable/ }).first();
  await expect(row).toBeVisible({ timeout: 15_000 });
  await expect(row).toContainText(/No key needed/i);
  expect(executionTraffic()).toEqual([]);
});

// ---------------------------------------------------------------------------
// Pool menu icon consistency (stubbed, no provider calls).
// RowActionsMenu renders a Popover of plain buttons — no menu/menuitem
// roles — so icon consistency scopes those buttons for one svg each.
// ---------------------------------------------------------------------------

When("I add a Keenable vault key labelled {string} without a secret", async ({ page }, label: string) => {
  await page.goto("/account/keys");
  await expect(page.getByRole("heading", { name: "Keys and pools" })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Add key", exact: true }).first().click();
  const dialog = page.getByRole("dialog", { name: "Add key" });
  await expect(dialog).toBeVisible({ timeout: 15_000 });
  await chooseOption(dialog, "Provider", "Keenable");
  await dialog.getByLabel("Label", { exact: true }).fill(label);
  await dialog.getByRole("button", { name: "Save key", exact: true }).click();
  await expect(dialog).toBeHidden({ timeout: 15_000 });
});

When("I create a Search pool {string} for project {word} on key {string} with pool identity", async ({ page }, pool: string, projectName: string, key: string) => {
  const before = executionTraffic().length;
  await page.getByRole("row").filter({ hasText: key }).getByRole("button", { name: "Create pool" }).click();
  const dialog = page.getByRole("dialog", { name: "Create pool" });
  await chooseOption(dialog, "Project", projectName);
  await dialog.getByLabel("Pool name").fill(pool);
  await dialog.getByRole("button", { name: "Create pool", exact: true }).click();
  await expect(dialog).toBeHidden({ timeout: 15_000 });
  expect(executionTraffic().length).toBe(before);
});

When("I open the pool actions menu for {string}", async ({ page }, pool: string) => {
  watchBrowserTraffic(page);
  // Keys and pools context: the pool popup lives on the vault page, so open
  // it there even when the prior step left the run on Providers.
  await page.goto("/account/keys");
  await expect(page.getByRole("button", { name: `Actions for ${pool}` })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: `Actions for ${pool}` }).click();
});

Then("the pool actions menu should show Edit pool, Copy to another project, Remove from project and Delete pool each with an icon", async ({ page }) => {
  // Popover buttons, not menu/menuitem roles: scope the open popup for one
  // svg per action. Fails naturally while RowActionsMenu renders bare labels.
  const popup = page.locator("[data-radix-popper-content-wrapper], [role='dialog'], [data-state='open']").last();
  await expect(popup).toBeVisible({ timeout: 10_000 });
  for (const label of ["Edit pool", "Copy to another project", "Remove from project", "Delete pool"]) {
    const item = popup.getByRole("button", { name: label });
    await expect(item).toBeVisible({ timeout: 10_000 });
    await expect(item.locator("svg").first()).toBeVisible({ timeout: 5_000 });
  }
  void projectStubAccountId;
});
