import { test as base, createBdd } from "playwright-bdd"

/**
 * Keep the BDD fixture surface in one place so every generated scenario uses
 * the same Playwright test instance and the shared browser context.
 */
export const test = base.extend({})

export const { Given, When, Then } = createBdd(test)
