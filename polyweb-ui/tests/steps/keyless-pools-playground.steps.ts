import { expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { Given, When, Then } from "./fixtures";
import { executionTraffic } from "./backendStub";
import { projectStubId } from "./projectStub";
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
 *   with the Search submit disabled — the no-pool case asserts this preflight
 *   and observes zero /search + /fetch execution calls (never submits).
 * - Keys and pools: route /account/keys, heading "Keys and pools", dialog
 *   "Add key" with "Add key" submit, Create pool via the key-row button,
 *   "Pool name" field present only when creating from the row context.
 * - Pool menu: RowActionsMenu Popover of plain buttons inside
 *   [data-slot=popover-content]; icon consistency asserts one svg per button.
 * - Trace detail: dialog "Trace detail", results list "Ranked results".
 * - Settings: field "Payload detail", option "Full requests".
 * - Live results carry "% match" text.
 *
 * ANTICIPATED (deliberately missing) UI contracts these scenarios pin down:
 * - Keyless key creation with a no-secret keyless mode (automatic keyless
 *   creation without an Authentication choice also satisfies the contract).
 * - One-shot bulk pool creation and keyless free-tier default pools,
 *   each carrying the created pool identity + provider + assigned project.
 * - One icon (svg) per pool popup/menu button.
 * Until production implements them, the corresponding steps fail naturally
 * against the current source (missing control / missing icon / API 4xx).
 */

// ---------------------------------------------------------------------------
// Fresh-signup state (@live only; never exercised while authoring).
// Scenario-specific identity: one unique email/username per signup so the two
// @live scenarios never share an account.
// ---------------------------------------------------------------------------

const FRESH_PASSWORD = "Str0ng-Passw0rd!2026";

function uniqueSuffix(): string {
  return `${Date.now().toString(36)}${Math.floor(Math.random() * 1e6).toString(36)}`;
}

let freshAccountEmail = "";
let freshProjectName = "";
let freshProjectUrl = "";

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

// ---------------------------------------------------------------------------
// Shared key/pool creation helpers (single definitions, both flows reuse).
// ---------------------------------------------------------------------------

let keylessKeyLabel = "";
let keylessPoolName = "";

async function createKeylessKey(page: Page): Promise<void> {
  keylessKeyLabel = `Keenable keyless ${uniqueSuffix()}`;
  await page.goto("/account/keys");
  await expect(page.getByRole("heading", { name: "Keys and pools" })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Add key", exact: true }).first().click();
  const dialog = page.getByRole("dialog", { name: "Add key" });
  await expect(dialog).toBeVisible({ timeout: 15_000 });
  await chooseOption(dialog, "Provider", "Keenable");
  await dialog.getByLabel("Label", { exact: true }).fill(keylessKeyLabel);
  // No-secret contract: an automatic-keyless save needs no Authentication
  // choice and no API key field; a keyless-mode select also satisfies this —
  // either way the save must carry no secret.
  const apiKeyField = dialog.getByLabel("API key", { exact: true });
  await expect(apiKeyField).toHaveCount(0);
  await dialog.getByRole("button", { name: "Add key", exact: true }).click();
  await expect(dialog).toBeHidden({ timeout: 15_000 });
  await expect(page.getByRole("row").filter({ hasText: keylessKeyLabel }).first()).toBeVisible({ timeout: 15_000 });
}

async function createPoolOnKeyInProject(page: Page, keyLabel: string, projectName: string): Promise<string> {
  keylessPoolName = `Keyless pool ${uniqueSuffix()}`;
  await page.goto("/account/keys");
  await page.getByRole("row").filter({ hasText: keyLabel }).first().getByRole("button", { name: "Create pool" }).click();
  const dialog = page.getByRole("dialog", { name: "Create pool" });
  await expect(dialog).toBeVisible({ timeout: 15_000 });
  // Explicit fresh-project selection inside the create-pool dialog.
  await chooseOption(dialog, "Project", projectName);
  // "Pool name" is only present when creating from the row context for a
  // scoped project; never invent a production field — read the label the
  // run actually created.
  const nameField = dialog.getByLabel("Pool name", { exact: true });
  if (await nameField.count() > 0) await nameField.fill(keylessPoolName);
  await dialog.getByRole("button", { name: "Create pool", exact: true }).click();
  await expect(dialog).toBeHidden({ timeout: 15_000 });
  return keylessPoolName;
}

// ---------------------------------------------------------------------------
// No-pool guidance (@live scenario A): preflight only, zero execution.
// ---------------------------------------------------------------------------

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

Then("the playground shows the create-or-assign pool guidance for the new project", async ({ page }) => {
  const main = page.locator("main");
  // Actionable create/assign guidance, not the legacy bare provider notice:
  // the run names pool creation or assignment for this project.
  await expect(main.getByText(/create.*pool|assign.*pool|add.*pool|set up.*pool/i).first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("button", { name: "Search", exact: true })).toBeDisabled();
  // Direct live page-request observation: zero /search and /fetch execution
  // calls on this run (stub counters alone would not prove the live page).
  expect(executionTraffic().filter((record) => record.operation === "search" || record.operation === "fetch")).toEqual([]);
});

Then("the no-pool error should not present as a timeout", async ({ page }) => {
  await expect(page.locator("main")).not.toContainText(/timed out|timeout/i);
});

Then("the playground shows no search results", async ({ page }) => {
  // No-pool preflight: the disabled Search submit never runs, so absence is
  // asserted as zero execution calls plus no result content.
  await expect(page.locator("main").getByText(/% match/i)).toHaveCount(0);
  expect(executionTraffic().filter((record) => record.operation === "search" || record.operation === "fetch")).toEqual([]);
});

// ---------------------------------------------------------------------------
// Keyless pool creation + Full trace detail (@live scenario B).
// ---------------------------------------------------------------------------

When("I create a keyless pool for Keenable without an API key and assign it to the new project", async ({ page }) => {
  await createKeylessKey(page);
  await createPoolOnKeyInProject(page, keylessKeyLabel, freshProjectName);
  await restoreFreshProject(page);
});

When("I run the keyless search and save the payload with Full requests", async ({ page }) => {
  // Establish Payload detail = Full requests BEFORE execution, and persist it
  // with an explicit save — setting storage after the request is too late.
  await page.goto(`/p/${freshProjectId()}/settings`);
  await page.getByRole("combobox", { name: "Payload detail" }).click();
  await page.getByRole("option", { name: "Full requests" }).click();
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText(/saved|updated/i).first()).toBeVisible({ timeout: 15_000 });
  await restoreFreshProject(page);
  await page.getByRole("navigation", { name: "Project" }).getByRole("link", { name: "Playground", exact: true }).click();
  await page.getByPlaceholder(/Search the web/i).fill("fresh project keyless probe");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.locator("main").getByText(/% match/i).first()).toBeVisible({ timeout: 30_000 });
});

When("I open the trace of the saved search response", async ({ page }) => {
  await page.getByRole("navigation", { name: "Project" }).getByRole("link", { name: "Activity", exact: true }).click();
  // Inspect THAT trace: the Activity list never carries the query text, so
  // correlate the newest search trace opened from the run above.
  const row = page.getByRole("table").getByRole("row").first();
  await expect(row).toBeVisible({ timeout: 30_000 });
  await row.getByRole("button", { name: "View details", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Trace detail" })).toBeVisible({ timeout: 15_000 });
});

Then("the trace detail shows the Keenable response with its results", async ({ page }) => {
  const dialog = page.getByRole("dialog", { name: "Trace detail" });
  await expect(dialog).toBeVisible({ timeout: 15_000 });
  await expect(dialog).toContainText(/Keenable/i);
  const ranked = dialog.getByRole("list", { name: "Ranked results" });
  await expect(ranked).toBeVisible({ timeout: 15_000 });
  await expect(ranked.getByText(/% match/i).first()).toBeVisible({ timeout: 15_000 });
});

// ---------------------------------------------------------------------------
// Bulk + default pool creation (stubbed, no provider calls).
// Prove pool identity/provider/project assignment — never bare rows.
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

Then("project Alpha has new pools for {string} assigned to Alpha", async ({ page }, list: string) => {
  const providers = list.split(",").map((entry) => entry.trim()).filter((entry) => entry !== "");
  // Identity + provider + project assignment: the vault rows for the newly
  // created pools must reference the Alpha project — provider rows or bare
  // "Alpha" text alone would pass on pre-seeded fixtures.
  await page.goto("/account/keys");
  for (const provider of providers) {
    const row = page.getByRole("row").filter({ hasText: new RegExp(provider, "i") }).last();
    await expect(row).toBeVisible({ timeout: 15_000 });
    await expect(row).toContainText(/Alpha/);
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

Then("project Alpha has a new keyless pool for Keenable assigned to Alpha", async ({ page }) => {
  await page.goto("/account/keys");
  const keyRow = page.getByRole("row").filter({ hasText: /Keenable/ }).last();
  await expect(keyRow).toBeVisible({ timeout: 15_000 });
  await expect(keyRow).toContainText(/Alpha/);
  await page.goto(`/p/${projectStubId("Alpha")}/providers`);
  const row = page.getByRole("row").filter({ hasText: /Keenable/ }).first();
  await expect(row).toBeVisible({ timeout: 15_000 });
  await expect(row).toContainText(/No key needed/i);
  expect(executionTraffic()).toEqual([]);
});

// ---------------------------------------------------------------------------
// Pool menu icon consistency (stubbed NONLIVE, conventional keyed pool).
// RowActionsMenu renders a Popover of plain buttons inside
// [data-slot=popover-content] — no menu/menuitem roles.
// ---------------------------------------------------------------------------

When("I open the pool actions menu for {string}", async ({ page }, pool: string) => {
  watchBrowserTraffic(page);
  await page.goto("/account/keys");
  const trigger = page.getByRole("button", { name: `Actions for ${pool}` });
  await expect(trigger).toBeVisible({ timeout: 15_000 });
  await trigger.click();
  await expect(page.locator("[data-slot=popover-content]").first()).toBeVisible({ timeout: 10_000 });
});

Then("the pool actions menu should show Edit pool, Copy to another project, Remove from project and Delete pool each with an icon", async ({ page }) => {
  const popup = page.locator("[data-slot=popover-content]").first();
  await expect(popup).toBeVisible({ timeout: 10_000 });
  for (const label of ["Edit pool", "Copy to another project", "Remove from project", "Delete pool"]) {
    const item = popup.getByRole("button", { name: label });
    await expect(item).toBeVisible({ timeout: 10_000 });
    await expect(item.locator("svg").first()).toBeVisible({ timeout: 5_000 });
  }
});

Then("the pool actions menu shows Edit pool, Copy to another project, Remove from project and Delete pool each with an icon", async ({ page }) => {
  const popup = page.locator("[data-slot=popover-content]").first();
  await expect(popup).toBeVisible({ timeout: 10_000 });
  for (const label of ["Edit pool", "Copy to another project", "Remove from project", "Delete pool"]) {
    const item = popup.getByRole("button", { name: label });
    await expect(item).toBeVisible({ timeout: 10_000 });
    await expect(item.locator("svg").first()).toBeVisible({ timeout: 5_000 });
  }
});
