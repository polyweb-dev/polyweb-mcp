import { expect } from "@playwright/test"
import type { Locator, Page } from "@playwright/test"
import type { DataTable } from "playwright-bdd"
import { Then, When } from "./fixtures"
import { projectStubId } from "./projectStub"
import { configRequests, credentialIdOf, grantsOf, stubLinks, stubPools } from "./providerConfigStub"
import { chooseOption, confirmIfAsked, fillField, labelledControl } from "./providerConfigUi"

/**
 * System credentials (grants) and Capacity (pools, links, allocations) steps
 * of the U3 contract. Credential create, rotate and OAuth steps are shared
 * with the project Providers page (project-providers.steps.ts,
 * credential-oauth.steps.ts).
 */

function tableRow(page: Page, tableName: string, text: string): Locator {
  return page.getByRole("table", { name: tableName, exact: true }).getByRole("row").filter({ hasText: text })
}

/** One pool link entry (list item or table row) with its Remove link action. */
function linkItem(page: Page, credential: string): Locator {
  return page
    .getByRole("listitem")
    .or(page.getByRole("row"))
    .filter({ hasText: credential })
    .filter({ has: page.getByRole("button", { name: "Remove link", exact: true }) })
}

function poolIdOf(label: string): string {
  const pool = stubPools().find((p) => p.label === label)
  if (pool === undefined) throw new Error(`unknown stub pool ${label}`)
  return pool.id
}

Then("the page URL path should not be {string}", async ({ page }, path: string) => {
  await expect(async () => {
    expect(new URL(page.url()).pathname).not.toBe(path)
  }).toPass({ timeout: 10_000 })
})

// --- System credentials ---------------------------------------------------

Then(
  "the system credentials table lists {string} with {string}",
  async ({ page }, label: string, text: string) => {
    const row = tableRow(page, "System credentials", label)
    await expect(row).toHaveCount(1, { timeout: 15_000 })
    await expect(row).toContainText(text)
  }
)

When("I open the grants of {string}", async ({ page }, label: string) => {
  await page.getByRole("button", { name: `Grants ${label}`, exact: true }).click({ timeout: 15_000 })
  await expect(page.getByText("Project grants", { exact: true }).first()).toBeVisible()
})

Then("the grants list {string} with {string}", async ({ page }, project: string, ops: string) => {
  const row = page
    .getByRole("row")
    .filter({ has: page.getByRole("button", { name: `Remove grant ${project}`, exact: true }) })
  await expect(row).toHaveCount(1, { timeout: 15_000 })
  await expect(row).toContainText(ops, { ignoreCase: true })
})

Then("the grant form offers {string} but not {string}", async ({ page }, offered: string, absent: string) => {
  await expect(page.getByRole("checkbox", { name: offered, exact: true })).toBeVisible()
  await expect(page.getByRole("checkbox", { name: absent, exact: true })).toHaveCount(0)
})

When("I remove the grant for {string}", async ({ page }, project: string) => {
  await page.getByRole("button", { name: `Remove grant ${project}`, exact: true }).click()
  await confirmIfAsked(page, "Remove grant")
})

Then("{string} has no grant for project {word}", async ({}, label: string, projectName: string) => {
  const projectId = projectStubId(projectName)
  await expect.poll(() => grantsOf(label).some((g) => g.project_id === projectId)).toBe(false)
})

When(
  "I grant project {string} the operations {string}",
  async ({ page }, project: string, ops: string) => {
    await chooseOption(page, "Project", project)
    const wanted = ops.split(",").map((s) => s.trim())
    for (const op of ["Search", "Fetch"]) {
      const box = page.getByRole("checkbox", { name: op, exact: true })
      if ((await box.count()) === 0) continue
      await box.setChecked(wanted.includes(op))
    }
    await page.getByRole("button", { name: "Save grant", exact: true }).click()
  }
)

Then(
  "the last grant request for project {word} permitted {string}",
  async ({}, projectName: string, ops: string) => {
    const path = new RegExp(`/grants/${projectStubId(projectName)}$`)
    await expect.poll(() => configRequests("PUT", path).length).toBeGreaterThan(0)
    const puts = configRequests("PUT", path)
    expect(puts[puts.length - 1].body).toEqual({ permitted_operations: ops.split(",").map((s) => s.trim()) })
  }
)

// --- Pools and links ------------------------------------------------------

Then("the pools table lists {string} with {string}", async ({ page }, label: string, text: string) => {
  const row = tableRow(page, "Pools", label)
  await expect(row).toHaveCount(1, { timeout: 15_000 })
  await expect(row).toContainText(text)
})

When("I add a pool with:", async ({ page }, table: DataTable) => {
  await page.getByRole("button", { name: "Add pool", exact: true }).click({ timeout: 15_000 })
  for (const { field, value } of table.hashes()) {
    if (field === "Algorithm" && (await page.getByRole("combobox", { name: "Algorithm", exact: true }).count()) === 0) {
      await page.getByRole("button", { name: "Add limit", exact: true }).click()
    }
    await fillField(page, field, value)
  }
  // The contract names no pool submit label; accept the conventional ones.
  await page.getByRole("button", { name: /^(Save pool|Create pool)$/ }).click()
})

Then("the last pool create request sent:", async ({}, doc: string) => {
  await expect.poll(() => configRequests("POST", /^\/api\/v1\/system\/pools$/).length).toBe(1)
  const body = configRequests("POST", /^\/api\/v1\/system\/pools$/)[0].body
  expect(body).toEqual(JSON.parse(doc))
})

When(
  "I link {string} for {string} to the pool {string}",
  async ({ page }, credential: string, op: string, pool: string) => {
    await page.getByRole("button", { name: `Links ${pool}`, exact: true }).click({ timeout: 15_000 })
    const linkButton = page.getByRole("button", { name: "Link credential", exact: true })
    if ((await page.getByRole("combobox", { name: "Credential", exact: true }).count()) === 0) await linkButton.click()
    await chooseOption(page, "Credential", credential)
    await chooseOption(page, "Operation", op)
    await linkButton.last().click()
  }
)

Then(
  "the pool {string} links {string} for {string}",
  async ({ page }, pool: string, credential: string, op: string) => {
    const path = new RegExp(`/pools/${poolIdOf(pool)}/links/${credentialIdOf(credential)}$`)
    await expect.poll(() => configRequests("PUT", path).length).toBe(1)
    expect(configRequests("PUT", path)[0].search).toBe(`?operation_scope=${op}`)
    const item = linkItem(page, credential)
    await expect(item).toHaveCount(1)
    await expect(item).toContainText(op)
  }
)

When("I remove the link of {string}", async ({ page }, credential: string) => {
  // The contract names no confirmation for unlinking.
  await linkItem(page, credential).getByRole("button", { name: "Remove link", exact: true }).click()
})

Then("the pool {string} has no links", async ({}, pool: string) => {
  const poolId = poolIdOf(pool)
  await expect.poll(() => stubLinks().filter((l) => l.pool_id === poolId).length).toBe(0)
})

// --- Allocations ----------------------------------------------------------

When("I show the allocations of project {word}", async ({ page }, projectName: string) => {
  await expect(page.getByRole("heading", { name: "Project allocations" })).toBeVisible({ timeout: 15_000 })
  await chooseOption(page, "Project", projectName)
})

When("I edit the allocation {string}", async ({ page }, name: string) => {
  await page.getByRole("button", { name: `Edit allocation ${name}`, exact: true }).click({ timeout: 15_000 })
})

Then("the allocation form {word} {string}", async ({ page }, visibility: string, label: string) => {
  const field = labelledControl(page, label)
  if (visibility === "shows") await expect(field).toBeVisible()
  else await expect(field).toHaveCount(0)
})

When("I choose the allocation mode {string}", async ({ page }, mode: string) => {
  await page.getByRole("radio", { name: mode, exact: true }).check()
})

async function fillAllocation(page: Page, table: DataTable): Promise<void> {
  for (const { field, value } of table.hashes()) await fillField(page, field, value)
}

When("I fill the allocation form with:", async ({ page }, table: DataTable) => {
  await fillAllocation(page, table)
})

When("I add an allocation with:", async ({ page }, table: DataTable) => {
  await page.getByRole("button", { name: "Add allocation", exact: true }).click({ timeout: 15_000 })
  await fillAllocation(page, table)
})

When("I tick best effort", async ({ page }) => {
  await page.getByLabel("Best effort", { exact: true }).check()
})

When("I save the allocation", async ({ page }) => {
  await page.getByRole("button", { name: "Save allocation", exact: true }).click()
})

Then("no allocation write was sent", async () => {
  expect(configRequests("PUT", /\/allocations\//)).toHaveLength(0)
})

Then(
  "the last allocation write for {string} {string} sent:",
  async ({}, pool: string, op: string, doc: string) => {
    const path = new RegExp(`/allocations/${poolIdOf(pool)}$`)
    await expect.poll(() => configRequests("PUT", path).length).toBeGreaterThan(0)
    const writes = configRequests("PUT", path)
    const last = writes[writes.length - 1]
    expect(last.search).toBe(`?operation_scope=${op}`)
    expect(last.body).toMatchObject(JSON.parse(doc) as Record<string, unknown>)
  }
)

Then("the Capacity page offers pool editing but no allocation editing", async ({ page }) => {
  await expect(page.getByRole("button", { name: "Add pool", exact: true })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole("button", { name: "Add allocation", exact: true })).toHaveCount(0)
  await expect(page.getByRole("button", { name: /^Edit allocation / })).toHaveCount(0)
  await expect(page.getByRole("button", { name: /^Remove allocation / })).toHaveCount(0)
})
