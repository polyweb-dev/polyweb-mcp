import { expect } from "@playwright/test";
import type { Page, Response, TestInfo } from "@playwright/test";
import { Before, Given, When, Then } from "./fixtures";
import { projectStubId } from "./projectStub";
import { chooseOption } from "./providerConfigUi";
import { lastCreatedPoolKeyLabel, lastCreatedPoolLabel, openVaultPoolDialog } from "./vault.steps";
import { seedVaultKey } from "./vaultStub";

interface PoolRecord {
  id: string;
  credential_id: string;
  provider_type: string;
  project_id: string;
  label: string;
}

interface KeyRecord { id: string; label: string; provider_type: string; auth_mode: string }
interface SearchRecord {
  traceId: string;
  query: string;
  provider: string;
  results: { title: string; url: string }[];
}
interface Evidence {
  execution: string[];
  external: string[];
  pools: Promise<PoolRecord>[];
  keys: Promise<KeyRecord>[];
  seededKeys: KeyRecord[];
  search: SearchRecord | null;
}

const evidenceByPage = new WeakMap<Page, Evidence>();
const PROVIDERS: Record<string, string> = { "Brave Search": "brave", Tavily: "tavily", Keenable: "keenable" };
const KEY_PATH = "/api/v1/account/vault/keys";
const POOL_PATH = /^\/api\/v1\/account\/vault\/keys\/[^/]+\/pools$/;

function evidence(page: Page): Evidence {
  const value = evidenceByPage.get(page);
  if (!value) throw new Error("TASK-000065 evidence was not initialized");
  return value;
}

Before({ tags: "@task-000065" }, async ({ page }) => {
  const value: Evidence = { execution: [], external: [], pools: [], keys: [], seededKeys: [], search: null };
  evidenceByPage.set(page, value);
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (request.method() === "POST" && /\/(search|fetch)\/?$/.test(url.pathname)) value.execution.push(request.url());
    if (["fetch", "xhr"].includes(request.resourceType()) && !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)) {
      value.external.push(request.url());
    }
  });
  page.on("response", (response) => {
    if (response.request().method() !== "POST" || !response.ok()) return;
    const path = new URL(response.url()).pathname;
    if (POOL_PATH.test(path)) value.pools.push(response.json());
    if (path === KEY_PATH) value.keys.push(response.json().then((key: KeyRecord) => {
      if (key.auth_mode === "keyless") expect(response.request().postDataJSON().secret ?? null).toBeNull();
      return key;
    }));
  });
});

function expectNoExecution(page: Page): void {
  expect(evidence(page).execution).toEqual([]);
  expect(evidence(page).external).toEqual([]);
}

/**
 * UI-evidence PNG helper (TASK-000065 Devin visual review, >=9 target).
 *
 * Captures at most one desktop PNG per call site and attaches it to the
 * running scenario via `$testInfo.attach`. Playwright writes attachments
 * under `test-results/` (picked up by `scripts/ci/upload_gitea.py` into
 * `reports.zip`); the HTML reporter also lists them in `playwright-report`.
 * Desktop-only: call sites never resize the viewport (worker runs
 * Desktop Chrome per playwright.config.ts). Cloud-only execution: this runs
 * inside the step on the CI worker, never locally.
 */
async function attachPng(page: Page, testInfo: TestInfo | undefined, name: string): Promise<void> {
  const path = await page.screenshot({ fullPage: false });
  await testInfo?.attach(name, { body: path, contentType: "image/png" });
}

function isResponse(response: Response, method: string, path: string): boolean {
  return response.request().method() === method && new URL(response.url()).pathname === path;
}

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
  await expect(page.getByRole("button", { name: `Select project (current: ${freshProjectName})`, exact: true })).toBeVisible({ timeout: 15_000 });
}

async function selectFreshProject(page: Page): Promise<void> {
  // ProjectCreateForm already navigates to the newly created project.
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

async function createKeylessKey(page: Page): Promise<void> {
  keylessKeyLabel = `Keenable keyless ${uniqueSuffix()}`;
  await page.goto("/account/keys");
  await expect(page.getByRole("heading", { name: "Keys and pools" })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Add key", exact: true }).first().click();
  const dialog = page.getByRole("dialog", { name: "Add key" });
  await expect(dialog).toBeVisible({ timeout: 15_000 });
  await chooseOption(dialog, "Provider", "Keenable");
  const authentication = dialog.getByRole("combobox", { name: "Authentication", exact: true });
  if (await authentication.count()) {
    await authentication.click();
    await page.getByRole("option", { name: /keyless|no (api )?key|free tier/i }).click();
  }
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

async function createPoolOnKeyInProject(page: Page, keyLabel: string, projectName: string): Promise<void> {
  const dialog = await openVaultPoolDialog(page, keyLabel);
  // Explicit fresh-project selection inside the create-pool dialog.
  await chooseOption(dialog, "Project", projectName);
  const key = (await Promise.all(evidence(page).keys)).find((entry) => entry.label === keyLabel);
  if (!key) throw new Error("The new keyless credential was not observed");
  expect(key).toMatchObject({ provider_type: "keenable", auth_mode: "keyless" });
  const responsePromise = page.waitForResponse((response) => isResponse(response, "POST", `${KEY_PATH}/${key.id}/pools`));
  await dialog.getByRole("button", { name: "Create pool", exact: true }).click();
  const response = await responsePromise;
  expect(response.ok()).toBe(true);
  expect(await response.json()).toMatchObject({ credential_id: key.id, provider_type: "keenable", project_id: freshProjectId() });
  await expect(dialog).toBeHidden({ timeout: 15_000 });
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
  expectNoExecution(page);
});

Then("the no-pool error should not present as a timeout", async ({ page }) => {
  await expect(page.locator("main")).not.toContainText(/timed out|timeout/i);
});

Then("the playground shows no search results", async ({ page, $testInfo }) => {
  // No-pool preflight: the disabled Search submit never runs, so absence is
  // asserted as zero execution calls plus no result content.
  await expect(page.locator("main").getByText(/% match/i)).toHaveCount(0);
  expectNoExecution(page);
  // Optional setup-state capture for the no-pool @live flow: runs only when
  // the live scenario itself is explicitly executed later.
  await attachPng(page, $testInfo, "task-000065-no-pool-guidance.png");
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
  await chooseOption(page, "Payload detail", "Full requests");
  const save = page.getByRole("button", { name: "Save changes", exact: true });
  if (await save.count()) {
    await save.click();
    await expect(save).toBeHidden();
  }
  await page.reload();
  await expect(page.getByRole("combobox", { name: "Payload detail" })).toContainText("Full requests");
  await restoreFreshProject(page);
  await page.getByRole("navigation", { name: "Project" }).getByRole("link", { name: "Playground", exact: true }).click();
  const query = `fresh project keyless probe ${uniqueSuffix()}`;
  await page.getByPlaceholder(/Search the web/i).fill(query);
  const responsePromise = page.waitForResponse((response) => response.request().method() === "POST" &&
    /\/search\/?$/.test(new URL(response.url()).pathname));
  await page.getByRole("button", { name: "Search", exact: true }).click();
  const response = await responsePromise;
  expect(response.ok()).toBe(true);
  const traceId = await response.headerValue("X-Trace-Id");
  expect(traceId).toMatch(/^[0-9a-f]{32}$/);
  const result = await response.json();
  expect(result).toMatchObject({ query, provider: "keenable" });
  expect(result.results.length).toBeGreaterThan(0);
  // Exactly one execution /search request: the evidence hook records only
  // POST calls whose path ends in /search (or /fetch), so its length is the
  // execution count with no separate counter.
  expect(evidence(page).execution).toHaveLength(1);
  evidence(page).search = { traceId: traceId!, query, provider: result.provider, results: result.results };
  await expect(page.locator("main").getByText(/% match/i).first()).toBeVisible({ timeout: 30_000 });
});

When("I open the trace of the saved search response", async ({ page }) => {
  const search = evidence(page).search;
  if (!search) throw new Error("Search response was not captured");
  const listPath = `/api/v1/projects/${freshProjectId()}/traces`;
  let index = -1;
  // Export is asynchronous. Locate the exact response trace in the UI's list
  // response, then open its corresponding body row (never the table header).
  await expect.poll(async () => {
    const listPromise = page.waitForResponse((response) => isResponse(response, "GET", listPath));
    await page.goto(`/p/${freshProjectId()}/activity`);
    const response = await listPromise;
    expect(response.ok()).toBe(true);
    const list = await response.json();
    index = list.items.findIndex((item: { trace_id: string }) => item.trace_id === search.traceId);
    return index;
  }, { timeout: 30_000 }).toBeGreaterThanOrEqual(0);
  const detailPromise = page.waitForResponse((response) => isResponse(response, "GET", `${listPath}/${search.traceId}`));
  await page.getByRole("table", { name: "Activity", exact: true }).locator("tbody > tr").nth(index)
    .getByRole("button", { name: "View details", exact: true }).click();
  const response = await detailPromise;
  expect(response.ok()).toBe(true);
  const detail = await response.json();
  expect(detail).toMatchObject({ trace_id: search.traceId, provider: search.provider, input: search.query });
  expect(detail.output).toMatchObject({ kind: "search_results", query: search.query });
  expect(detail.output.results.map((result: { url: string }) => result.url)).toEqual(search.results.map((result) => result.url));
  await expect(page.getByRole("dialog", { name: "Trace detail" })).toBeVisible({ timeout: 15_000 });
});

Then("the trace detail shows the Keenable response with its results", async ({ page, $testInfo }) => {
  const dialog = page.getByRole("dialog", { name: "Trace detail" });
  await expect(dialog).toBeVisible({ timeout: 15_000 });
  await expect(dialog).toContainText(/Keenable/i);
  const ranked = dialog.getByRole("list", { name: "Ranked results" });
  await expect(ranked).toBeVisible({ timeout: 15_000 });
  const search = evidence(page).search;
  if (!search) throw new Error("Search response was not captured");
  expect(search.results[0].title).not.toBe("");
  await expect(ranked.getByText(search.results[0].title, { exact: true }).first()).toBeVisible();
  // Optional result-state capture for the keyless @live flow: runs only when
  // the live scenario itself is explicitly executed later.
  await attachPng(page, $testInfo, "task-000065-keyless-trace-results.png");
});

// ---------------------------------------------------------------------------
// Bulk + default pool creation (stubbed, no provider calls).
// Prove pool identity/provider/project assignment — never bare rows.
// ---------------------------------------------------------------------------

Given("I have vault keys for {string}", async ({ page }, list: string) => {
  for (const name of list.split(",").map((entry) => entry.trim())) {
    const provider = PROVIDERS[name];
    if (!provider) throw new Error(`Unsupported test provider: ${name}`);
    evidence(page).seededKeys.push(seedVaultKey(provider, `Bulk ${name}`, provider === "keenable" ? "keyless" : "api_key"));
  }
});

Then("no vendor request should have been made", async ({ page }) => {
  expectNoExecution(page);
});

When("I bulk create pools for {string} for project Alpha without provider calls", async ({ page, $testInfo }, list: string) => {
  const providers = list.split(",").map((entry) => entry.trim()).filter((entry) => entry !== "");
  expect(providers.length).toBeGreaterThan(1);
  await page.goto("/account/keys");
  await expect(page.getByRole("heading", { name: "Keys and pools" })).toBeVisible({ timeout: 15_000 });
  // Anticipated bulk contract: one dialog creates pools for several
  // providers at once. Fails naturally while only per-key Create pool exists.
  await page.getByRole("button", { name: /Bulk create pools/i }).click();
  const dialog = page.getByRole("dialog", { name: /Bulk create pools/i });
  await expect(dialog).toBeVisible({ timeout: 10_000 });
  await chooseOption(dialog, "Project", "Alpha");
  for (const provider of providers) {
    await dialog.getByRole("checkbox", { name: provider, exact: false }).check();
  }
  // Visual evidence (non-live, cloud only): bulk dialog after the project and
  // provider choices, before submission. Single PNG per scenario.
  await attachPng(page, $testInfo, "task-000065-bulk-dialog.png");
  await dialog.getByRole("button", { name: /^Create(?: \d+)? pools?$/i }).click();
  await expect(dialog).toBeHidden({ timeout: 15_000 });
  expectNoExecution(page);
});

async function expectCreatedPools(page: Page, providers: string[]): Promise<void> {
  const state = evidence(page);
  const pools = await Promise.all(state.pools);
  const keys = [...state.seededKeys, ...await Promise.all(state.keys)];
  expect(pools).toHaveLength(providers.length);
  expect(new Set(pools.map((pool) => pool.id)).size).toBe(providers.length);
  expect(pools.map((pool) => pool.provider_type).sort()).toEqual([...providers].sort());
  await page.goto("/account/keys");
  for (const pool of pools) {
    expect(pool.id).toEqual(expect.any(String));
    expect(pool.project_id).toBe(projectStubId("Alpha"));
    const key = keys.find((candidate) => candidate.id === pool.credential_id);
    if (!key) throw new Error(`No observed credential owns created pool ${pool.id}`);
    expect(key.provider_type).toBe(pool.provider_type);
    const toggle = page.getByRole("button", { name: `Pools of ${key.label}`, exact: true });
    if (await toggle.getAttribute("aria-expanded") !== "true") await toggle.click();
    // This scenario starts without pools and creates exactly one per key.
    const row = toggle.locator("xpath=ancestor::tr/following-sibling::tr[1]");
    await expect(row.getByRole("button", { name: `Actions for ${pool.label}`, exact: true })).toBeVisible();
    await expect(row).toContainText("Alpha");
  }
  expectNoExecution(page);
}

Then("project Alpha has new pools for {string} assigned to Alpha", async ({ page }, list: string) => {
  await expectCreatedPools(page, list.split(",").map((entry) => PROVIDERS[entry.trim()]));
});

When("I create the keyless free-tier default pools for project Alpha without an API key", async ({ page, $testInfo }) => {
  await page.goto("/account/keys");
  await expect(page.getByRole("heading", { name: "Keys and pools" })).toBeVisible({ timeout: 15_000 });
  // Anticipated defaults contract: one control provisions the supported
  // keyless free-tier pools with no secret. Fails naturally while missing.
  await page.getByRole("button", { name: /Create keyless defaults/i }).click();
  const dialog = page.getByRole("dialog", { name: /Keyless defaults|Default pools/i });
  await expect(dialog).toBeVisible({ timeout: 10_000 });
  await chooseOption(dialog, "Project", "Alpha");
  await expect(dialog.getByLabel("API key", { exact: true })).toHaveCount(0);
  // Visual evidence (non-live, cloud only): defaults modal after the project
  // selection, showing no secret, before submission. Single PNG per scenario.
  await attachPng(page, $testInfo, "task-000065-keyless-defaults-dialog.png");
  await dialog.getByRole("button", { name: /Create|Save/i }).click();
  await expect(dialog).toBeHidden({ timeout: 15_000 });
  expectNoExecution(page);
});

Then("project Alpha has new keyless pools for {string} assigned to Alpha", async ({ page }, list: string) => {
  const providers = list.split(",").map((entry) => PROVIDERS[entry.trim()]);
  const keys = await Promise.all(evidence(page).keys);
  expect(keys).toHaveLength(providers.length);
  expect(keys.every((key) => key.auth_mode === "keyless")).toBe(true);
  await expectCreatedPools(page, providers);
});

// ---------------------------------------------------------------------------
// Pool menu icon consistency (stubbed NONLIVE, conventional keyed pool).
// RowActionsMenu renders a Popover of plain buttons inside
// [data-slot=popover-content] — no menu/menuitem roles.
// ---------------------------------------------------------------------------

When("I open the pool actions menu for the created pool", async ({ page }) => {
  await page.goto("/account/keys");
  await expect(page.getByRole("heading", { name: "Keys and pools" })).toBeVisible({ timeout: 15_000 });
  // The pool popover lives inside the expanded key row's pools table: open
  // the key row first, then the created pool's own Actions trigger.
  await page.getByRole("button", { name: `Pools of ${lastCreatedPoolKeyLabel()}` }).click();
  const trigger = page.getByRole("button", { name: `Actions for ${lastCreatedPoolLabel()}` });
  await expect(trigger).toBeVisible({ timeout: 15_000 });
  await trigger.click();
  await expect(page.locator("[data-slot=popover-content]").first()).toBeVisible({ timeout: 10_000 });
});

Then("the pool actions menu should show Edit pool, Copy to another project, Remove from project and Delete pool each with an icon", async ({ page, $testInfo }) => {
  const popup = page.locator("[data-slot=popover-content]").first();
  await expect(popup).toBeVisible({ timeout: 10_000 });
  for (const label of ["Edit pool", "Copy to another project", "Remove from project", "Delete pool"]) {
    const item = popup.getByRole("button", { name: label });
    await expect(item).toBeVisible({ timeout: 10_000 });
    await expect(item.locator("svg").first()).toBeVisible({ timeout: 5_000 });
  }
  expectNoExecution(page);
  // Visual evidence (non-live, cloud only): pool table with the rate column
  // and the open action popover showing its icons. Single PNG per scenario.
  await attachPng(page, $testInfo, "task-000065-pool-popover-icons.png");
});
