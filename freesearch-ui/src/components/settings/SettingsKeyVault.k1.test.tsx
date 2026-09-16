import React from "react"
import { readFileSync } from "node:fs"
import path from "node:path"
import { describe, expect, it, afterEach, vi } from "vitest"
import { render, screen, within, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { ToastContainer } from "@/components/common/ToastContainer"
import { SettingsView } from "./SettingsView"
import { installFetchStub, ok, err, deferred, type FetchStub } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
  secretStatusFixture,
} from "@/test/backendFixtures"

/**
 * K1 Keys wasted space — BDD Acceptance (RED phase).
 *
 * User bullet (verbatim): "Wasted space" (Keys tab). Read-only:
 * .agents/FEEDBACK/UI/feedback.md L26. SEE image yourself:
 * .agents/FEEDBACK/UI/image-5.png (cards stacked left, right void).
 *
 * BUG image-5.png shows the Key vault cards stacked in a single left column
 * with an empty void on the right — the section is capped at max-w-4xl and
 * the grid is single-column (`grid gap-3`) so it never fills the available
 * width at desktop viewports.
 *
 * Plan under test (ONLY SettingsKeyVault.tsx, freesearch-ui/ ONLY):
 *   L49 section (max-w-4xl -> w-full max-w-none) +
 *   L57 grid (+sm:grid-cols-2 items-start). No other changes.
 *
 * AC mapping:
 *   K1-1  available-width section — <section> carries w-full + max-w-none
 *           and NO capped max-w (no max-w-4xl, no other max-w-* except
 *           max-w-none). Source + rendered DOM token assertions.
 *           RED: current L49 is `space-y-4 max-w-4xl` (no w-full, no
 *           max-w-none, capped) so every K1-1 assertion FAILS cleanly.
 *   K1-2  two-column grid — L57 grid div gains sm:grid-cols-2 +
 *           items-start while KEEPING grid + gap-3. Source + rendered DOM
 *           token assertions. RED: current grid is `grid gap-3` with no
 *           sm:grid-cols-2/items-start, so the new-token assertions FAIL
 *           cleanly while the keep-grid/gap-3 assertions PASS (keep-guard).
 *   K1-3  1440px fills main — at window.innerWidth 1440 the rendered
 *           section + grid still carry the K1 width tokens and all 7 key
 *           cards sit in the full-width grid. jsdom has no layout engine so
 *           the executable proxy is the width-class invariant at the 1440px
 *           viewport (same structural-invariant approach as S-P4-3); pixel
 *           proof needs a browser (Playwright). RED: fails on the missing
 *           w-full/max-w-none/sm:grid-cols-2 tokens.
 *   K1-4  375px single-column, no overflow — below sm the grid stays
 *           single-column (sm: prefix only, no base grid-cols-2) and the
 *           cards cannot overflow horizontally (inputs flex-1 min-w-48,
 *           button rows flex-wrap, fingerprints truncate, no fixed widths).
 *           The sm:-token assertions FAIL in Red; the no-overflow guards
 *           PASS before and after (keep-guards).
 *   K1-5  behavior contract (GREEN in Red phase — must stay GREEN after):
 *           heading + write-only description, per-provider input labels,
 *           Save disabled on blank/whitespace, save PUTs exactly {key} and
 *           renders the SERVER fingerprint while clearing the write-only
 *           input, save pending shows Saving..., delete DELETEs and marks
 *           Missing, delete pending shows Working..., NO environment/dotenv
 *           hint of any kind plus the exact "Key stored in the encrypted vault."
 *           success toast, loading skeleton (aria-busy + disabled Delete
 *           key), exact status pills (6x Stored + 1x Keyless, no Missing),
 *           masked fingerprints with no reveal actions, exact placeholders.
 *   K1-6  regression guards (must stay GREEN before and after):
 *           Providers S-P4 intact (section w-full max-w-none, frame w-full
 *           max-w-none + overflow-hidden, table min-w-[960px]), Failover
 *           Failover spans full width (F1), SettingsView pills
 *           (Providers/Keys/Failover pill variant), Carbon Black tokens, NO
 *           ProviderMatrix merge, freesearch-ui ONLY (no backend/python
 *           imports, no absolute backend literals).
 *
 * RED expectation:
 *   K1-1 FAILS cleanly (section capped max-w-4xl, no w-full/max-w-none).
 *   K1-2 FAILS cleanly on sm:grid-cols-2/items-start (grid+gap-3 keep PASSES).
 *   K1-3 FAILS cleanly (width tokens missing at 1440px).
 *   K1-4a FAILS cleanly (sm:grid-cols-2 missing at 375px); K1-4b PASSES.
 *   K1-5 + K1-6 PASS (behaviors + prior bullets intact).
 */

const testDir = import.meta.dirname
const keyVaultSource = readFileSync(path.resolve(testDir, "./SettingsKeyVault.tsx"), "utf8")
const providersSource = readFileSync(path.resolve(testDir, "./SettingsProviders.tsx"), "utf8")
const failoverSource = readFileSync(path.resolve(testDir, "./SettingsFailover.tsx"), "utf8")
const indexCssSource = readFileSync(path.resolve(testDir, "../../index.css"), "utf8")
// P1-FINAL (DELETE collateral, NOT a regression): ProviderMatrix.tsx is
// DELETED by the merge, so no test may read it at module scope (the read
// would throw Green and fail the whole file on collection).

const norm = (value: string): string => value.toLowerCase().replace(/\s+/g, "")

const SEED_PROVIDER_NAMES = [
  "Brave Search",
  "Keenable",
  "Tavily",
  "Exa",
  "Firecrawl",
  "You.com",
  "Parallel",
] as const

const STANDARD_PLACEHOLDER = "Paste an API key to store"
const KEYLESS_PLACEHOLDER = "Optional — store a key to bypass the free tier"

const ORIGINAL_INNER_WIDTH = window.innerWidth

let secretSource: string = "encrypted_db"
let putGate: Promise<Response> | null = null
let deleteGate: Promise<Response> | null = null
const gateHolder: { providers: ReturnType<typeof deferred<Response>> | null } = {
  providers: null,
}

function renderSettings(deferProviders = false): FetchStub {
  secretSource = "encrypted_db"
  putGate = null
  deleteGate = null
  gateHolder.providers = deferProviders ? deferred<Response>() : null
  const stub = installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      if (gateHolder.providers) return gateHolder.providers.promise
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    if (req.url.endsWith("/secret") && req.method === "PUT") {
      if (putGate) return putGate
      const provider = req.url.split("/").at(-2) ?? "unknown"
      return ok(
        secretStatusFixture({
          provider,
          fingerprint: `${provider.slice(0, 3).toUpperCase()}_••••••••a1b2`,
          source: secretSource,
        })
      )
    }
    if (req.url.endsWith("/secret") && req.method === "DELETE") {
      if (deleteGate) return deleteGate
      const provider = req.url.split("/").at(-2) ?? "unknown"
      return ok(
        secretStatusFixture({
          provider,
          presence: "missing",
          fingerprint: null,
          source: "none",
        })
      )
    }
    if (req.method === "POST" && req.url.endsWith("/test")) {
      return ok({
        provider: "brave",
        ok: true,
        status: "healthy",
        latency_ms: 142,
        checked_at: "2026-09-06T10:04:00Z",
        detail: null,
      })
    }
    if (req.method === "PUT" && req.url === "/api/v1/routing/config") {
      return ok({ ...routingConfigFixture(), ...((req.body as object) ?? {}) })
    }
    return err(404, { detail: "unhandled test route" })
  })
  render(
    <FreeSearchProvider>
      <SettingsView />
      <ToastContainer />
    </FreeSearchProvider>
  )
  return stub
}

async function waitForProviders() {
  await waitFor(() => {
    expect(screen.getByText("Brave Search", { exact: true })).toBeInTheDocument()
  })
}

async function openKeysTab() {
  await userEvent.setup().click(screen.getByRole("tab", { name: /^Keys$/ }))
}

/** Exact class-token list for an element (Tailwind tokens are whitespace-separated). */
function classTokens(el: Element): string[] {
  return (el.getAttribute("class") ?? "").split(/\s+/).filter(Boolean)
}

/** L49 <section className="..."> token list from source. */
function sectionClassFromSource(): string[] {
  const match = keyVaultSource.match(/<section\s+className="([^"]*)"/)
  if (!match) throw new Error("<section className> not found in SettingsKeyVault.tsx (L49 moved?)")
  return match[1].split(/\s+/).filter(Boolean)
}

/** L57 grid <div className="...grid..."> token list from source. */
function gridClassFromSource(): string[] {
  const matches = [...keyVaultSource.matchAll(/<div\s+className="([^"]*)"/g)]
  const grid = matches.map((m) => m[1]).find((cls) => cls.split(/\s+/).includes("grid"))
  if (!grid) throw new Error("Grid <div> with grid token not found in SettingsKeyVault.tsx (L57 moved?)")
  return grid.split(/\s+/).filter(Boolean)
}

function keyVaultSection(): HTMLElement {
  const heading = screen.getByRole("heading", { name: "Key vault" })
  const section = heading.closest("section")
  if (!section) throw new Error("Key vault <section> not found around the heading")
  return section as HTMLElement
}

function keyVaultGrid(): HTMLElement {
  const grid = keyVaultSection().querySelector("div.grid")
  if (!grid) throw new Error("Key vault grid div.grid not found inside the section")
  return grid as HTMLElement
}

function findKeyCard(provider: string): HTMLElement {
  const providerName = screen.getByText(provider, { exact: true })
  let current = providerName.parentElement
  while (current && current !== document.body) {
    if (current.querySelector('input[type="password"]')) return current as HTMLElement
    current = current.parentElement
  }
  throw new Error(`Key card not found for ${provider}`)
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  gateHolder.providers = null
  ;(window.innerWidth as number) = ORIGINAL_INNER_WIDTH
  window.dispatchEvent(new Event("resize"))
})

// ---------------------------------------------------------------------------
// K1-1: section spans the available width (RED)
// ---------------------------------------------------------------------------

describe("K1-1: key vault section spans available width (w-full max-w-none, no cap)", () => {
  it("section source carries w-full", () => {
    expect(
      sectionClassFromSource(),
      `L49 section must carry w-full; got ${JSON.stringify(sectionClassFromSource())}`
    ).toContain("w-full")
  })

  it("section source carries max-w-none", () => {
    expect(
      sectionClassFromSource(),
      `L49 section must carry max-w-none; got ${JSON.stringify(sectionClassFromSource())}`
    ).toContain("max-w-none")
  })

  it("section source has no capped max-w (no max-w-4xl, no other max-w-* but max-w-none)", () => {
    const tokens = sectionClassFromSource()
    expect(tokens, "L49 section must not keep max-w-4xl").not.toContain("max-w-4xl")
    expect(tokens, "section must not be capped at max-w-3xl").not.toContain("max-w-3xl")
    expect(tokens, "section must not be capped at max-w-5xl").not.toContain("max-w-5xl")
    const capped = tokens.filter((t) => /^max-w-/.test(t) && t !== "max-w-none")
    expect(capped, `section must have no capped max-w-*, got ${JSON.stringify(tokens)}`).toEqual([])
  })

  it("rendered section carries w-full + max-w-none with no capped max-w", async () => {
    renderSettings()
    await waitForProviders()
    await openKeysTab()
    const tokens = classTokens(keyVaultSection())
    expect(tokens, `rendered section must carry w-full; got ${JSON.stringify(tokens)}`).toContain(
      "w-full"
    )
    expect(
      tokens,
      `rendered section must carry max-w-none; got ${JSON.stringify(tokens)}`
    ).toContain("max-w-none")
    const capped = tokens.filter((t) => /^max-w-/.test(t) && t !== "max-w-none")
    expect(capped, `rendered section must have no capped max-w-*; got ${JSON.stringify(tokens)}`).toEqual(
      []
    )
  })
})

// ---------------------------------------------------------------------------
// K1-2: grid goes two-column at sm (RED on new tokens)
// ---------------------------------------------------------------------------

describe("K1-2: key card grid fills with sm:grid-cols-2 items-start", () => {
  it("grid source carries sm:grid-cols-2", () => {
    expect(
      gridClassFromSource(),
      `L57 grid must carry sm:grid-cols-2; got ${JSON.stringify(gridClassFromSource())}`
    ).toContain("sm:grid-cols-2")
  })

  it("grid source carries items-start", () => {
    expect(
      gridClassFromSource(),
      `L57 grid must carry items-start; got ${JSON.stringify(gridClassFromSource())}`
    ).toContain("items-start")
  })

  it("grid source KEEPS grid + gap-3 (card rhythm contract)", () => {
    const tokens = gridClassFromSource()
    expect(tokens, `grid must keep grid; got ${JSON.stringify(tokens)}`).toContain("grid")
    expect(tokens, `grid must keep gap-3; got ${JSON.stringify(tokens)}`).toContain("gap-3")
  })

  it("rendered grid carries sm:grid-cols-2 + items-start and keeps grid gap-3", async () => {
    renderSettings()
    await waitForProviders()
    await openKeysTab()
    const tokens = classTokens(keyVaultGrid())
    expect(tokens, `rendered grid must carry sm:grid-cols-2; got ${JSON.stringify(tokens)}`).toContain(
      "sm:grid-cols-2"
    )
    expect(tokens, `rendered grid must carry items-start; got ${JSON.stringify(tokens)}`).toContain(
      "items-start"
    )
    expect(tokens, `rendered grid must keep grid; got ${JSON.stringify(tokens)}`).toContain("grid")
    expect(tokens, `rendered grid must keep gap-3; got ${JSON.stringify(tokens)}`).toContain("gap-3")
  })
})

// ---------------------------------------------------------------------------
// K1-3: 1440px viewport fills the main column (RED on width)
// ---------------------------------------------------------------------------

describe("K1-3: 1440px viewport fills the Settings main column", () => {
  it("at 1440px the section + grid still carry the K1 width tokens with no cap", async () => {
    ;(window.innerWidth as number) = 1440
    window.dispatchEvent(new Event("resize"))
    renderSettings()
    await waitForProviders()
    await openKeysTab()
    const sectionTokens = classTokens(keyVaultSection())
    const gridTokens = classTokens(keyVaultGrid())
    expect(
      sectionTokens,
      `1440px section must carry w-full; got ${JSON.stringify(sectionTokens)}`
    ).toContain("w-full")
    expect(
      sectionTokens,
      `1440px section must carry max-w-none; got ${JSON.stringify(sectionTokens)}`
    ).toContain("max-w-none")
    expect(
      sectionTokens.filter((t) => /^max-w-/.test(t) && t !== "max-w-none"),
      `1440px section must have no capped max-w-*; got ${JSON.stringify(sectionTokens)}`
    ).toEqual([])
    expect(
      gridTokens,
      `1440px grid must carry sm:grid-cols-2; got ${JSON.stringify(gridTokens)}`
    ).toContain("sm:grid-cols-2")
    expect(
      gridTokens,
      `1440px grid must carry items-start; got ${JSON.stringify(gridTokens)}`
    ).toContain("items-start")
  })

  it("at 1440px all 7 key cards sit in the full-width grid", async () => {
    ;(window.innerWidth as number) = 1440
    window.dispatchEvent(new Event("resize"))
    renderSettings()
    await waitForProviders()
    await openKeysTab()
    const grid = keyVaultGrid()
    expect(grid.querySelectorAll('input[type="password"]')).toHaveLength(7)
    expect(grid.children).toHaveLength(7)
    for (const name of SEED_PROVIDER_NAMES) {
      expect(within(grid).getByText(name, { exact: true })).toBeInTheDocument()
    }
  })
})

// ---------------------------------------------------------------------------
// K1-4: 375px viewport stays single-column with no overflow
// ---------------------------------------------------------------------------

describe("K1-4: 375px viewport stays single-column with no overflow", () => {
  it("at 375px the grid keeps the sm: prefix (no base grid-cols-2, single column)", async () => {
    ;(window.innerWidth as number) = 375
    window.dispatchEvent(new Event("resize"))
    renderSettings()
    await waitForProviders()
    await openKeysTab()
    const tokens = classTokens(keyVaultGrid())
    expect(tokens, `375px grid must carry sm:grid-cols-2; got ${JSON.stringify(tokens)}`).toContain(
      "sm:grid-cols-2"
    )
    expect(tokens, `375px grid must not have a base grid-cols-2; got ${JSON.stringify(tokens)}`).not.toContain(
      "grid-cols-2"
    )
    expect(tokens, `375px grid must not jump to md:grid-cols-2; got ${JSON.stringify(tokens)}`).not.toContain(
      "md:grid-cols-2"
    )
  })

  it("at 375px the cards cannot overflow horizontally (flex-wrap, flex-1 min-w-48, truncate)", async () => {
    ;(window.innerWidth as number) = 375
    window.dispatchEvent(new Event("resize"))
    renderSettings()
    await waitForProviders()
    await openKeysTab()
    for (const name of SEED_PROVIDER_NAMES) {
      const card = findKeyCard(name)
      const input = card.querySelector('input[type="password"]') as HTMLInputElement | null
      expect(input, `${name} card must have a password input`).not.toBeNull()
      expect(input!.className).toMatch(/flex-1/)
      expect(input!.className).toMatch(/min-w-48/)
      const saveButton = within(card).getByRole("button", { name: /^(Save|Saving\.\.\.)$/ })
      expect(saveButton.parentElement!.className).toMatch(/flex-wrap/)
      expect(card.querySelector("span.truncate"), `${name} fingerprint must truncate`).not.toBeNull()
    }
    const gridTokens = classTokens(keyVaultGrid())
    expect(
      gridTokens.filter((t) => /^max-w-/.test(t)),
      `grid must carry no max-w cap; got ${JSON.stringify(gridTokens)}`
    ).toEqual([])
    expect(gridTokens.some((t) => /^w-\[/.test(t)), `grid must carry no fixed width; got ${JSON.stringify(gridTokens)}`).toBe(
      false
    )
  })
})

// ---------------------------------------------------------------------------
// K1-5: behavior contract (GREEN in Red phase)
// ---------------------------------------------------------------------------

describe("K1-5: key vault behavior contract", () => {
  it("renders the Key vault heading with the write-only description", async () => {
    renderSettings()
    await waitForProviders()
    await openKeysTab()
    expect(screen.getByRole("heading", { name: "Key vault" })).toBeInTheDocument()
    expect(
      screen.getByText("Credentials are write-only: paste to store, and only a masked fingerprint is kept.", {
        exact: true,
      })
    ).toBeInTheDocument()
  })

  it("labels all 7 key inputs with their provider name", async () => {
    renderSettings()
    await waitForProviders()
    await openKeysTab()
    for (const name of SEED_PROVIDER_NAMES) {
      const input = screen.getByRole("textbox", { name: `${name} API key` })
      expect(input.getAttribute("type")).toBe("password")
      expect(input.getAttribute("aria-label")).toBe(`${name} API key`)
    }
  })

  it("uses exact placeholders (keyless hint for Keenable, standard for the rest)", async () => {
    renderSettings()
    await waitForProviders()
    await openKeysTab()
    expect(screen.getByRole("textbox", { name: "Keenable API key" })).toHaveAttribute(
      "placeholder",
      KEYLESS_PLACEHOLDER
    )
    for (const name of SEED_PROVIDER_NAMES.filter((n) => n !== "Keenable")) {
      expect(screen.getByRole("textbox", { name: `${name} API key` })).toHaveAttribute(
        "placeholder",
        STANDARD_PLACEHOLDER
      )
    }
  })

  it("disables Save on blank and on whitespace-only drafts", async () => {
    const user = userEvent.setup()
    renderSettings()
    await waitForProviders()
    await openKeysTab()
    const card = findKeyCard("You.com")
    expect(within(card).getByRole("button", { name: /^Save$/ })).toBeDisabled()
    await user.type(card.querySelector('input[type="password"]') as HTMLInputElement, "   ")
    expect(within(card).getByRole("button", { name: /^Save$/ })).toBeDisabled()
  })

  it("saves a key with the SERVER fingerprint and clears the write-only input", async () => {
    const user = userEvent.setup()
    const stub = renderSettings()
    await waitForProviders()
    await openKeysTab()
    const card = findKeyCard("You.com")
    const input = card.querySelector('input[type="password"]') as HTMLInputElement
    await user.type(input, "yc_live_secret_key_6789")
    await user.click(within(card).getByRole("button", { name: /^Save$/ }))
    await waitFor(() => {
      expect(within(card).getByText("YOU_••••••••a1b2", { exact: true })).toBeInTheDocument()
    })
    expect(within(card).getByText("Stored", { exact: true })).toBeInTheDocument()
    expect(input).toHaveValue("")
    expect(document.body.textContent).not.toContain("yc_live_secret_key_6789")
    const puts = stub.requestsTo("/api/v1/providers/you/secret")
    expect(puts).toHaveLength(1)
    expect(puts[0].method).toBe("PUT")
    expect(puts[0].body).toEqual({ key: "yc_live_secret_key_6789" })
  })

  it("shows Saving... on the Save button while the PUT is in flight", async () => {
    const user = userEvent.setup()
    renderSettings()
    await waitForProviders()
    await openKeysTab()
    const gate = deferred<Response>()
    putGate = gate.promise
    const card = findKeyCard("You.com")
    await user.type(card.querySelector('input[type="password"]') as HTMLInputElement, "yc_live_secret_key_6789")
    await user.click(within(card).getByRole("button", { name: /^Save$/ }))
    await waitFor(() => {
      expect(within(card).getByRole("button", { name: /^Saving\.\.\.$/ })).toBeInTheDocument()
    })
    gate.resolve(
      ok(secretStatusFixture({ provider: "you", fingerprint: "YOU_••••••••a1b2", source: "encrypted_db" }))
    )
    await waitFor(() => {
      expect(within(card).getByText("YOU_••••••••a1b2", { exact: true })).toBeInTheDocument()
    })
  })

  it("exposes a Delete secret button per key card that DELETEs and marks Missing", async () => {
    const user = userEvent.setup()
    const stub = renderSettings()
    await waitForProviders()
    await openKeysTab()
    const card = findKeyCard("Tavily")
    await user.click(within(card).getByRole("button", { name: /^Delete key$/ }))
    await waitFor(() => {
      expect(within(card).getByText("Missing", { exact: true })).toBeInTheDocument()
    })
    const deletes = stub.requestsTo("/api/v1/providers/tavily/secret")
    expect(deletes).toHaveLength(1)
    expect(deletes[0].method).toBe("DELETE")
  })

  it("shows Working... on the Delete button while the DELETE is in flight", async () => {
    const user = userEvent.setup()
    renderSettings()
    await waitForProviders()
    await openKeysTab()
    const gate = deferred<Response>()
    deleteGate = gate.promise
    const card = findKeyCard("Tavily")
    await user.click(within(card).getByRole("button", { name: /^Delete key$/ }))
    await waitFor(() => {
      expect(within(card).getByRole("button", { name: /^Working\.\.\.$/ })).toBeInTheDocument()
    })
    gate.resolve(
      ok(secretStatusFixture({ provider: "tavily", presence: "missing", fingerprint: null, source: "none" }))
    )
    await waitFor(() => {
      expect(within(card).getByText("Missing", { exact: true })).toBeInTheDocument()
    })
  })

  it("shows no environment/dotenv hint and the exact vault toast after save", async () => {
    const user = userEvent.setup()
    renderSettings()
    await waitForProviders()
    await openKeysTab()
    secretSource = "environment"
    const card = findKeyCard("Exa")
    await user.type(card.querySelector('input[type="password"]') as HTMLInputElement, "exa-live-key")
    await user.click(within(card).getByRole("button", { name: /^Save$/ }))
    await waitFor(() => {
      expect(
        within(card).getByText("EXA_••••••••a1b2", { exact: true })
      ).toBeInTheDocument()
    })
    // Vault-only: no legacy-source hint may appear anywhere in the UI.
    expect(card.textContent).not.toMatch(/environment|dotenv/i)
    expect(document.body.textContent).not.toMatch(/shadow/i)
    await waitFor(() => {
      expect(
        screen.getByText("Key stored in the encrypted vault.", { exact: true })
      ).toBeInTheDocument()
    })
  })

  it("renders the loading skeleton with aria-busy and a disabled Delete key, then resolves to 7 cards", async () => {
    const user = userEvent.setup()
    renderSettings(true)
    await user.click(screen.getByRole("tab", { name: /^Keys$/ }))
    expect(screen.getByText("Loading provider keys...", { exact: true })).toBeInTheDocument()
    const busy = screen
      .getByText("Loading provider keys...", { exact: true })
      .closest("[aria-busy]")
    expect(busy?.getAttribute("aria-busy")).toBe("true")
    const section = keyVaultSection()
    expect(
      within(section).getByRole("button", { name: /^Delete key$/ })
    ).toBeDisabled()
    gateHolder.providers!.resolve(ok(allProvidersFixture()))
    await waitForProviders()
    expect(screen.queryByText("Loading provider keys...", { exact: true })).not.toBeInTheDocument()
    expect(keyVaultGrid().querySelectorAll('input[type="password"]')).toHaveLength(7)
  })

  it("shows exact status pills (6x Stored + 1x Keyless, no Missing) with masked fingerprints and no reveal actions", async () => {
    renderSettings()
    await waitForProviders()
    await openKeysTab()
    expect(screen.getAllByText("Stored", { exact: true })).toHaveLength(6)
    expect(screen.getByText("Keyless", { exact: true })).toBeInTheDocument()
    expect(screen.queryByText("Missing", { exact: true })).not.toBeInTheDocument()
    expect(screen.getAllByText(/••••••••/)).toHaveLength(6)
    const body = document.body.textContent ?? ""
    for (const forbidden of ["Copy", "Burn", "Reveal", "shown once"]) {
      expect(body).not.toContain(forbidden)
    }
  })
})

// ---------------------------------------------------------------------------
// K1-6: regression guards — Providers S-P4, Failover cap, pills, theme
// ---------------------------------------------------------------------------

describe("K1-6: no regression — Providers S-P4, Failover cap, pills, theme, scope", () => {
  it("Providers P1-FINAL intact: merged registry section + frame keep w-full max-w-none with overflow-hidden", async () => {
    renderSettings()
    await waitForProviders()
    const table = screen.getByRole("table")
    const section = table.closest("section") as HTMLElement
    const sectionTokens = classTokens(section)
    expect(sectionTokens).toContain("w-full")
    expect(sectionTokens).toContain("max-w-none")
    expect(sectionTokens.filter((t) => /^max-w-/.test(t) && t !== "max-w-none")).toEqual([])
    const container = table.closest('[data-slot="table-container"]') as HTMLElement | null
    expect(container, "ui/table scroller must wrap the provider table").not.toBeNull()
    const frameTokens = classTokens(container!.parentElement as HTMLElement)
    expect(frameTokens).toContain("w-full")
    expect(frameTokens).toContain("max-w-none")
    expect(frameTokens).toContain("overflow-hidden")
    expect(table.className).toMatch(/min-w-\[960px\]/)
    expect(providersSource).toContain("w-full max-w-none")
  })

  it("Failover spans full width like Providers/Keys (F1 overrides the old max-w-3xl cap)", () => {
    const match = failoverSource.match(/<section\s+className="([^"]*)"/)
    if (!match) throw new Error("<section className> not found in SettingsFailover.tsx")
    const tokens = match[1].split(/\s+/).filter(Boolean)
    expect(tokens, `Failover section must gain w-full; got ${JSON.stringify(tokens)}`).toContain(
      "w-full"
    )
    expect(tokens, `Failover section must gain max-w-none; got ${JSON.stringify(tokens)}`).toContain(
      "max-w-none"
    )
    expect(
      tokens.filter((t) => /^max-w-/.test(t) && t !== "max-w-none"),
      `Failover section must drop max-w-3xl; got ${JSON.stringify(tokens)}`
    ).toEqual([])
  })

  it("SettingsView pills stay Providers/Keys/Failover on the pill variant", async () => {
    renderSettings()
    await waitForProviders()
    expect(screen.getAllByRole("tab")).toHaveLength(3)
    for (const label of ["Providers", "Keys", "Failover"]) {
      expect(screen.getByRole("tab", { name: new RegExp(`^${label}$`) })).toBeInTheDocument()
    }
    const pillList = document.querySelector('[data-slot="tabs-list"][data-variant="pill"]')
    expect(pillList, "pill tablist must exist").not.toBeNull()
    expect(
      within(pillList as HTMLElement)
        .getAllByRole("tab")
        .map((t) => t.textContent)
    ).toEqual(["Providers", "Keys", "Failover"])
    expect(
      document.querySelectorAll('[data-slot="tabs-list"][data-variant="line"]')
    ).toHaveLength(0)
  })

  it("Carbon Black theme tokens untouched (#1e1e1e scale + #007acc, no oklch)", () => {
    expect(norm(indexCssSource).includes("#1e1e1e")).toBe(true)
    expect(norm(indexCssSource).includes("#252526")).toBe(true)
    expect(norm(indexCssSource).includes("#3e3e42")).toBe(true)
    expect(norm(indexCssSource).includes("#007acc")).toBe(true)
    expect(norm(indexCssSource).includes("oklch(")).toBe(false)
  })

  it("P1-FINAL scope: SettingsKeyVault never imports the retired ProviderMatrix or sibling sections", () => {
    expect(keyVaultSource).not.toMatch(/ProviderMatrix/)
    expect(keyVaultSource).not.toMatch(/SettingsProviders/)
    expect(keyVaultSource).not.toMatch(/SettingsFailover/)
  })

  it("freesearch-ui ONLY: SettingsKeyVault imports no backend/python paths or absolute backend literals", () => {
    expect(keyVaultSource).not.toMatch(/\.py["']/)
    expect(keyVaultSource).not.toMatch(/src\/freesearch/)
    expect(keyVaultSource).not.toMatch(/127\.0\.0\.1/)
  })
})
