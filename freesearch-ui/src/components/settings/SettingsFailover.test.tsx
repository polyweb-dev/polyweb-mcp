import React from "react"
import { readFileSync } from "node:fs"
import path from "node:path"
import { describe, expect, it, afterEach, vi } from "vitest"
import { render, screen, within, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { ADMIN_ACCOUNT_ID, DEVELOPER_ACCOUNT_ID } from "@/test/authFixtures"
import { SettingsView } from "./SettingsView"
import { installFetchStub, ok, err, type FetchStub } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
} from "@/test/backendFixtures"

describe("SettingsFailover.f1f2.test.tsx", () => {

/**
 * F1+F2 Failover failover — BDD Acceptance (RED phase).
 *
 * User bullets (verbatim): F1 "Wasted space" + F2 "improper separation
 * between text and boxes below". Read-only:
 * .agents/FEEDBACK/UI/feedback.md L29-32. SEE images yourself:
 * .agents/FEEDBACK/UI/image-6.png (failover cards hug the left ~50%, right
 * void) + .agents/FEEDBACK/UI/image-27.png (honest explainer <p> touches the
 * Cascade/Timeout card below it).
 *
 * ORCHESTRATOR DECISION (overrides any keep-cap): Failover goes FULL-WIDTH
 * like Providers (S-P4) and Keys (K1) — section max-w-3xl -> w-full
 * max-w-none. Failover behaviors/copy/switches untouched.
 *
 * Plan under test (ONLY SettingsFailover.tsx, freesearch-ui/ ONLY):
 *   F1  L13 section (max-w-3xl -> w-full max-w-none).
 *   F2  explainer <p> (L55) + Cascade/Timeout card (L59) get a caption gap:
 *       space-y-2 wrapper or equivalent breathing. Copy unchanged, card rows
 *       untouched.
 *
 * AC mapping:
 *   F1-1  available-width section — <section> carries w-full + max-w-none
 *           and NO capped max-w (no max-w-3xl, no other max-w-* except
 *           max-w-none). Source + rendered DOM token assertions.
 *           RED: current L13 is `space-y-4 max-w-3xl` (no w-full, no
 *           max-w-none, capped) so every F1-1 assertion FAILS cleanly.
 *   F1-2  cards stay full-column (GREEN in Red phase — must stay GREEN
 *           after): the two cards keep stacking vertically (no multi-column
 *           grid), carry no max-w cap of their own, and the section keeps its
 *           space-y-4 stack rhythm. PASSES before and after.
 *   F1-3  1440px fills main — at window.innerWidth 1440 the rendered
 *           section still carries w-full max-w-none with no cap and both
 *           cards sit inside it. jsdom has no layout engine so the executable
 *           proxy is the width-class invariant at the 1440px viewport (same
 *           structural-invariant approach as S-P4-3/K1-3); pixel proof needs
 *           a browser (Playwright). RED: fails on the missing
 *           w-full/max-w-none tokens.
 *   F1-4  375px no horizontal overflow hazards (GREEN in Red phase): the
 *           failover subtree carries no fixed-width hazards (no min-w-[*],
 *           no w-[Npx], no whitespace-nowrap/truncate) so nothing can push a
 *           375px viewport into h-scroll. PASSES before and after.
 *   F2-1  caption breathing grows the gap (RED): a DEDICATED caption gap
 *           exists between the explainer <p> and the Cascade/Timeout card —
 *           a wrapper carrying space-y-n/gap-n (e.g. space-y-2) around the
 *           pair, OR explicit vertical breathing on the explainer (mb-n/pb-n)
 *           OR on the card (mt-n/pt-n). Scoped so the section-level space-y-4
 *           and the row-internal gap-4 do NOT count. RED: none exists, so the
 *           breathing set is [] and the assertion FAILS cleanly.
 *   F2-2  no overlap keep-guard (GREEN in Red phase): explainer renders
 *           strictly before the card in DOM order, no negative-margin tokens
 *           (-mt-n/-space-n) anywhere between them, and their boxes never
 *           intersect (jsdom returns zero rects, so the rect check is
 *           zeros-or-separated; pixel proof needs Playwright). PASSES before
 *           and after.
 *   F2-3  copy identical (GREEN in Red phase): exact honest explainer copy,
 *           exact header copy, exact per-switch descriptions, exact cascade /
 *           timeout values, invented "3,000 ms" budget absent everywhere.
 *           PASSES before and after (the plan changes copy NOWHERE).
 *   F2-4  card rows untouched (GREEN in Red phase): the Cascade/Timeout card
 *           keeps exactly 2 rows with exact labels/values and exact row
 *           layout tokens (flex items-center justify-between py-3 gap-4,
 *           divide-y container). PASSES before and after.
 *   B-1..B-4  behavior contract (GREEN in Red phase — must stay GREEN
 *           after): exactly 4 switches with exact labels/descriptions and
 *           all-on initial state (B-1); master toggle PUTs the exact routing
 *           body and flips the honest description + cascade hops text both
 *           ways (B-2); per-condition toggles are session-only — zero PUTs —
 *           while flipping aria-checked and leaving the rest intact (B-3);
 *           keyboard operability — all 4 switches are enabled <button>s and
 *           Space on the focused master toggles it (B-4).
 *   G-1..G-5  regression guards (must stay GREEN before and after):
 *           Providers S-P4 intact (section w-full max-w-none, frame w-full
 *           max-w-none + overflow-hidden, table min-w-[880px]) (G-1); Keys K1
 *           intact (section w-full max-w-none, grid sm:grid-cols-2) (G-2);
 *           SettingsView pills (Providers/Keys/Failover pill variant) (G-3);
 *           Carbon Black tokens (#1e1e1e scale + #007acc, no oklch) (G-4); NO
 *           page merge + freesearch-ui ONLY (no backend/python paths,
 *           no absolute backend literals) (G-5).
 *
 * RED expectation:
 *   F1-1 FAILS cleanly (section capped max-w-3xl, no w-full/max-w-none).
 *   F1-3 FAILS cleanly (width tokens missing at 1440px).
 *   F2-1 FAILS cleanly (no caption breathing tokens).
 *   F1-2, F1-4, F2-2, F2-3, F2-4, B-*, G-* PASS (stack/copy/behaviors/guards
 *   intact). The 2 blessed guard updates (K1 L631-644, S-P4 L515-520) FAIL
 *   cleanly in Red by design — they now pin the F1 full-width end state.
 */

const testDir = import.meta.dirname
const failoverSource = readFileSync(path.resolve(testDir, "./SettingsFailover.tsx"), "utf8")
const settingsSource = readFileSync(path.resolve(testDir, "./SettingsProviders.tsx"), "utf8")
// Slice 4: registry siblings own rows/modal/controls; the merge markers run
// against the union of the registry feature owners.
const settingsFeatureSource = [
  settingsSource,
  readFileSync(path.resolve(testDir, "./ProviderRegistryRow.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderRegistryHeader.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderTestModal.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderTestModalDetail.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderHealthStatus.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderPriorityControl.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderRowPill.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./ProviderOperationControl.tsx"), "utf8"),
  readFileSync(path.resolve(testDir, "./providerDisplay.ts"), "utf8"),
].join("\n")
// P1-FINAL (blessed inversion): ProviderMatrix.tsx is DELETED by the merge —
// no test may read it (the file is gone Green). The G-5 guard below now pins
// the merged end-state instead of the retired split.
const keyVaultSource = readFileSync(path.resolve(testDir, "./SettingsKeyVault.tsx"), "utf8")
const settingsViewSource = readFileSync(path.resolve(testDir, "./SettingsView.tsx"), "utf8")
const indexCssSource = readFileSync(path.resolve(testDir, "../../index.css"), "utf8")

const norm = (value: string): string => value.toLowerCase().replace(/\s+/g, "")

// ---------------------------------------------------------------------------
// Exact honest copy (must never change — F2-3 pins every string).
// ---------------------------------------------------------------------------

const EXPLAINER_COPY =
  "Backend dispatch currently makes a single attempt per request; it does not retry across providers. Per-condition switches are session-only — not enforced by the backend."
const MASTER_ON_COPY =
  "Persisted backend policy. Current backend dispatch performs a single attempt per request (no cross-provider retry)."
const MASTER_OFF_COPY =
  "Persisted backend policy: single-attempt dispatch against the selected provider."
const RATE_LIMIT_COPY = "Moves to the next provider when upstream returns HTTP 429."
const TIMEOUT_COPY = "Moves on when a provider exceeds its local timeout."
const SERVER_ERROR_COPY = "Moves on when upstream reports a server-side failure."
const CASCADE_ON_TEXT = "Up to 3 fallback hops"
const CASCADE_OFF_TEXT = "1 hop (single-shot)"
const TIMEOUT_VALUE = "Timeout budget not exposed by backend"

const ORIGINAL_INNER_WIDTH = window.innerWidth

function renderSettings(): FetchStub {
  const stub = installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    if (req.method === "PATCH" && req.url.startsWith("/api/v1/providers/")) {
      const backendId = req.url.split("/").at(-1) ?? "unknown"
      const wire = allProvidersFixture().find((p) => p.provider_id === backendId)
      const base = { ...(wire ?? allProvidersFixture()[0]) } as Record<string, unknown> & {
        enable_mask: number
        priority: number
      }
      const patch = ((req.body as Record<string, unknown>) ?? {}) as Record<string, unknown>
      let enableMask = base.enable_mask
      if (typeof patch.enable_mask === "number") enableMask = patch.enable_mask
      else {
        if (patch.enabled === true) enableMask |= 1
        if (patch.enabled === false) enableMask &= ~1
        if (patch.search_enabled === true) enableMask |= 2
        if (patch.search_enabled === false) enableMask &= ~2
        if (patch.fetch_enabled === true) enableMask |= 4
        if (patch.fetch_enabled === false) enableMask &= ~4
      }
      const priority = typeof patch.priority === "number" ? patch.priority : base.priority
      return ok({ ...base, enable_mask: enableMask, enabled: (enableMask & 1) !== 0, priority })
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
    <FreeSearchProvider accountId={ADMIN_ACCOUNT_ID} canReadControls canEditControls>
      <SettingsView />
    </FreeSearchProvider>
  )
  return stub
}

async function waitForProviders() {
  await waitFor(() => {
    expect(screen.getByText("Brave Search", { exact: true })).toBeInTheDocument()
  })
}

async function openFailover() {
  await userEvent.setup().click(screen.getByRole("tab", { name: /^Failover$/ }))
  await waitFor(() => {
    expect(
      screen.getByRole("heading", { name: "Failover policy" })
    ).toBeInTheDocument()
  })
}

/** Exact class-token list for an element (Tailwind tokens are whitespace-separated). */
function classTokens(el: Element): string[] {
  return (el.getAttribute("class") ?? "").split(/\s+/).filter(Boolean)
}

/** L13 <section className="..."> token list from source. */
function failoverSectionTokensFromSource(): string[] {
  const match = failoverSource.match(/<section\s+className="([^"]*)"/)
  if (!match) throw new Error("<section className> not found in SettingsFailover.tsx (L13 moved?)")
  return match[1].split(/\s+/).filter(Boolean)
}

function cappedMaxWidthTokens(tokens: string[]): string[] {
  return tokens.filter((t) => /^max-w-/.test(t) && t !== "max-w-none")
}

function failoverSection(): HTMLElement {
  const heading = screen.getByRole("heading", { name: "Failover policy" })
  const section = heading.closest("section")
  if (!section) throw new Error("Failover <section> not found around the heading")
  return section as HTMLElement
}

function explainerPara(): HTMLElement {
  const node = screen.getByText(/Backend dispatch currently makes a single attempt/)
  const para = node.closest("p")
  if (!para) throw new Error("Explainer <p> not found around the honest copy")
  return para as HTMLElement
}

/** The switches card: rounded-lg container holding "Fallback chaining". */
function switchesCard(): HTMLElement {
  const label = screen.getByText("Fallback chaining", { exact: true })
  let current = label.parentElement
  while (current && current !== document.body) {
    if (
      current.tagName === "DIV" &&
      classTokens(current).includes("rounded-lg") &&
      current.textContent?.includes("Failover on server error (5xx)")
    ) {
      return current as HTMLElement
    }
    current = current.parentElement
  }
  throw new Error("Switches card (rounded-lg, holding all 4 switches) not found")
}

/** The Cascade/Timeout card: rounded-lg container holding BOTH Cascade depth and Timeout budget. */
function cascadeCard(): HTMLElement {
  const label = screen.getByText("Cascade depth", { exact: true })
  let current = label.parentElement
  while (current && current !== document.body) {
    if (
      current.tagName === "DIV" &&
      classTokens(current).includes("rounded-lg") &&
      current.textContent?.includes("Timeout budget")
    ) {
      return current as HTMLElement
    }
    current = current.parentElement
  }
  throw new Error("Cascade/Timeout card (rounded-lg, holding both rows) not found")
}

/**
 * DEDICATED caption breathing between the explainer <p> and the
 * Cascade/Timeout card — a space-y-2-style wrapper around the pair, or
 * explicit vertical breathing on the explainer (mb-n/pb-n) or on the card
 * (mt-n/pt-n). The section-level space-y-4 and the row-internal gap-4 are
 * deliberately OUT of scope here (they exist today and still leave the
 * caption touching the card in image-27).
 */
function captionBreathingTokens(): string[] {
  const explainer = explainerPara()
  const card = cascadeCard()
  const found: string[] = []

  const explainerTokens = classTokens(explainer).filter((t) => /^[mp][bt]-/.test(t))
  found.push(...explainerTokens)

  const cardTokens = classTokens(card).filter((t) => /^[mp][bt]-/.test(t))
  found.push(...cardTokens)

  // A dedicated wrapper holds BOTH nodes but is NOT the top-level section.
  const section = failoverSection()
  let cursor = explainer.parentElement
  while (cursor && cursor !== section && cursor !== document.body) {
    if (cursor.contains(card)) {
      found.push(
        ...classTokens(cursor).filter((t) => /^(space-y-.+|gap-.+|m[bt]-.+|p[bt]-.+)$/.test(t))
      )
      break
    }
    cursor = cursor.parentElement
  }
  return found
}

/** Source-level mirror: breathing classNames strictly between </p> and the cascade card. */
function captionBreathingTokensFromSource(): string[] {
  const explainerMatch = failoverSource.match(
    /<p\s+className="([^"]*)">\s*Backend dispatch currently makes a single attempt/
  )
  if (!explainerMatch) throw new Error("Explainer <p className> not found in SettingsFailover.tsx")
  const explainerTokens = explainerMatch[1]
    .split(/\s+/)
    .filter(Boolean)
    .filter((t) => /^[mp][bt]-/.test(t))

  const cardMatch = failoverSource.match(/<div\s+className="([^"]*divide-y[^"]*)"/)
  if (!cardMatch) throw new Error("Cascade card <div className> (divide-y) not found")
  const cardTokens = cardMatch[1]
    .split(/\s+/)
    .filter(Boolean)
    .filter((t) => /^[mp][bt]-/.test(t))

  const explainerEnd =
    failoverSource.indexOf("not enforced by the backend.") + "not enforced by the backend.".length
  const cardOpen = failoverSource.indexOf('<div className="rounded-lg border', explainerEnd)
  if (explainerEnd === -1 || cardOpen === -1 || cardOpen <= explainerEnd) {
    throw new Error("Caption region (explainer </p> .. cascade card <div>) not found")
  }
  const region = failoverSource.slice(explainerEnd, cardOpen)
  const wrapperTokens = [...region.matchAll(/className="([^"]*)"/g)]
    .flatMap((m) => m[1].split(/\s+/).filter(Boolean))
    .filter((t) => /^(space-y-.+|gap-.+|m[bt]-.+|p[bt]-.+)$/.test(t))

  return [...explainerTokens, ...cardTokens, ...wrapperTokens]
}

function routingConfigPuts(stub: FetchStub) {
  return stub.requests.filter((r) => r.method === "PUT" && r.url === "/api/v1/routing/config")
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  ;(window.innerWidth as number) = ORIGINAL_INNER_WIDTH
  window.dispatchEvent(new Event("resize"))
})

// ---------------------------------------------------------------------------
// F1-1: section spans the available width (RED)
// ---------------------------------------------------------------------------

describe("F1-1: Failover section spans the available width", () => {
  it("source: section carries w-full + max-w-none with no capped max-w", () => {
    const tokens = failoverSectionTokensFromSource()
    expect(tokens, `Failover section must gain w-full; got ${JSON.stringify(tokens)}`).toContain(
      "w-full"
    )
    expect(
      tokens,
      `Failover section must gain max-w-none; got ${JSON.stringify(tokens)}`
    ).toContain("max-w-none")
    expect(
      cappedMaxWidthTokens(tokens),
      `Failover section must drop max-w-3xl; got ${JSON.stringify(tokens)}`
    ).toEqual([])
  })

  it("rendered: section carries w-full + max-w-none with no capped max-w", async () => {
    renderSettings()
    await waitForProviders()
    await openFailover()
    const tokens = classTokens(failoverSection())
    expect(tokens, `Rendered section must gain w-full; got ${JSON.stringify(tokens)}`).toContain(
      "w-full"
    )
    expect(
      tokens,
      `Rendered section must gain max-w-none; got ${JSON.stringify(tokens)}`
    ).toContain("max-w-none")
    expect(
      cappedMaxWidthTokens(tokens),
      `Rendered section must drop max-w-3xl; got ${JSON.stringify(tokens)}`
    ).toEqual([])
  })
})

// ---------------------------------------------------------------------------
// F1-2: cards stay full-column (GREEN keep-guard)
// ---------------------------------------------------------------------------

describe("F1-2: cards stay stacked full-column with no caps of their own", () => {
  it("both cards stack vertically: no multi-column grid, no card-level max-w, exactly 2 cards", async () => {
    renderSettings()
    await waitForProviders()
    await openFailover()
    const section = failoverSection()
    const sectionTokens = classTokens(section)
    expect(
      sectionTokens.filter((t) => /^(sm:)?grid-cols-/.test(t)),
      `Failover section must stay single-column; got ${JSON.stringify(sectionTokens)}`
    ).toEqual([])

    const cards = Array.from(section.querySelectorAll("div.rounded-lg.border")) as HTMLElement[]
    expect(cards).toHaveLength(2)
    for (const card of cards) {
      expect(
        cappedMaxWidthTokens(classTokens(card)),
        `Card must carry no max-w cap; got ${JSON.stringify(classTokens(card))}`
      ).toEqual([])
    }
    expect(section).toContainElement(switchesCard())
    expect(section).toContainElement(cascadeCard())
  })

  it("section keeps its space-y-4 vertical stack rhythm", async () => {
    renderSettings()
    await waitForProviders()
    await openFailover()
    expect(classTokens(failoverSection())).toContain("space-y-4")
    expect(failoverSectionTokensFromSource()).toContain("space-y-4")
  })
})

// ---------------------------------------------------------------------------
// F1-3: 1440px fills the main column (RED)
// ---------------------------------------------------------------------------

describe("F1-3: 1440px viewport fills the main column", () => {
  it("width-class invariant holds at 1440px with both cards inside the full-width section", async () => {
    ;(window.innerWidth as number) = 1440
    window.dispatchEvent(new Event("resize"))
    renderSettings()
    await waitForProviders()
    await openFailover()
    const section = failoverSection()
    const tokens = classTokens(section)
    expect(tokens, `1440px: section must carry w-full; got ${JSON.stringify(tokens)}`).toContain(
      "w-full"
    )
    expect(
      tokens,
      `1440px: section must carry max-w-none; got ${JSON.stringify(tokens)}`
    ).toContain("max-w-none")
    expect(
      cappedMaxWidthTokens(tokens),
      `1440px: section must carry no capped max-w; got ${JSON.stringify(tokens)}`
    ).toEqual([])
    expect(section).toContainElement(switchesCard())
    expect(section).toContainElement(cascadeCard())
    expect(failoverSectionTokensFromSource()).toContain("w-full")
  })
})

// ---------------------------------------------------------------------------
// F1-4: 375px has no horizontal-overflow hazards (GREEN keep-guard)
// ---------------------------------------------------------------------------

describe("F1-4: 375px viewport has no horizontal overflow hazards", () => {
  it("failover subtree carries no fixed-width hazards and wraps long copy", async () => {
    ;(window.innerWidth as number) = 375
    window.dispatchEvent(new Event("resize"))
    renderSettings()
    await waitForProviders()
    await openFailover()
    const section = failoverSection()
    const descendants = [section, ...Array.from(section.querySelectorAll("*"))] as Element[]
    const tokenList = descendants.flatMap((el) => classTokens(el))
    expect(
      tokenList.filter((t) => /^min-w-\[/.test(t)),
      "No fixed min-w-[*] may constrain the 375px viewport"
    ).toEqual([])
    expect(
      tokenList.filter((t) => /^w-\[\d+(px|rem)\]$/.test(t)),
      "No fixed w-[Npx] may constrain the 375px viewport"
    ).toEqual([])
    expect(
      tokenList.filter((t) => t === "whitespace-nowrap" || t === "truncate"),
      "Long honest copy must wrap, never force h-scroll"
    ).toEqual([])
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(375)
  })
})

// ---------------------------------------------------------------------------
// F2-1: caption breathing between explainer and card (RED)
// ---------------------------------------------------------------------------

describe("F2-1: explainer and Cascade/Timeout card gain caption breathing", () => {
  it("source: dedicated caption breathing exists between </p> and the cascade card", () => {
    const breathing = captionBreathingTokensFromSource()
    expect(
      breathing,
      "Failover must wrap the explainer + cascade card in a space-y-2 (or equivalent " +
        "mb-*/mt-*/gap-*) caption gap; the section space-y-4 and row gap-4 do not count"
    ).not.toEqual([])
  })

  it("rendered: dedicated caption breathing exists between <p> and the cascade card", async () => {
    renderSettings()
    await waitForProviders()
    await openFailover()
    const breathing = captionBreathingTokens()
    expect(
      breathing,
      "Rendered failover must carry caption breathing (space-y-2 wrapper or explicit " +
        "mb-*/mt-*) between the explainer and the Cascade/Timeout card"
    ).not.toEqual([])
  })
})

// ---------------------------------------------------------------------------
// F2-2: no overlap keep-guard (GREEN)
// ---------------------------------------------------------------------------

describe("F2-2: explainer never overlaps the card", () => {
  it("DOM order is explainer-then-card with no negative-margin tricks and non-intersecting boxes", async () => {
    renderSettings()
    await waitForProviders()
    await openFailover()
    const explainer = explainerPara()
    const card = cascadeCard()
    expect(explainer.tagName).toBe("P")
    expect(
      explainer.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy()
    const between = [...failoverSource.matchAll(/-(mt|space)-/g)].map((m) => m[0])
    expect(between).toEqual([])
    const explainerRect = explainer.getBoundingClientRect()
    const cardRect = card.getBoundingClientRect()
    const noLayoutEngine =
      explainerRect.width === 0 &&
      explainerRect.height === 0 &&
      cardRect.width === 0 &&
      cardRect.height === 0
    expect(
      noLayoutEngine || explainerRect.bottom <= cardRect.top,
      `Explainer bottom (${explainerRect.bottom}) must sit above card top (${cardRect.top})`
    ).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// F2-3: copy identical (GREEN keep-guard)
// ---------------------------------------------------------------------------

describe("F2-3: honest copy is byte-identical", () => {
  it("explainer, headers, switch descriptions, and policy values match exactly", async () => {
    renderSettings()
    await waitForProviders()
    await openFailover()
    expect(explainerPara().textContent).toBe(EXPLAINER_COPY)
    expect(screen.getByRole("heading", { name: "Failover policy" })).toBeInTheDocument()
    expect(
      screen.getByText("How the resolver reacts when a selected provider fails.", { exact: true })
    ).toBeInTheDocument()
    expect(screen.getByText(MASTER_ON_COPY, { exact: true })).toBeInTheDocument()
    expect(screen.getByText(RATE_LIMIT_COPY, { exact: true })).toBeInTheDocument()
    expect(screen.getByText(TIMEOUT_COPY, { exact: true })).toBeInTheDocument()
    expect(screen.getByText(SERVER_ERROR_COPY, { exact: true })).toBeInTheDocument()
    expect(screen.getByText("Cascade depth", { exact: true })).toBeInTheDocument()
    expect(screen.getByText(CASCADE_ON_TEXT, { exact: true })).toBeInTheDocument()
    expect(screen.getByText("Timeout budget", { exact: true })).toBeInTheDocument()
    expect(screen.getByText(TIMEOUT_VALUE, { exact: true })).toBeInTheDocument()
  })

  it("the invented per-hop timeout budget is gone everywhere", async () => {
    renderSettings()
    await waitForProviders()
    await openFailover()
    expect(screen.queryByText("3,000 ms", { exact: true })).not.toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/3,\s?000\s?ms/)
  })
})

// ---------------------------------------------------------------------------
// F2-4: card rows untouched (GREEN keep-guard)
// ---------------------------------------------------------------------------

describe("F2-4: Cascade/Timeout card rows are untouched", () => {
  it("card keeps exactly 2 rows with exact layout tokens and divide-y container", async () => {
    renderSettings()
    await waitForProviders()
    await openFailover()
    const card = cascadeCard()
    expect(classTokens(card)).toContain("divide-y")
    const rows = Array.from(card.children).filter((el) => el.textContent?.includes("Cascade depth") || el.textContent?.includes("Timeout budget"))
    expect(rows).toHaveLength(2)
    for (const row of rows) {
      const tokens = classTokens(row)
      for (const required of ["flex", "items-center", "justify-between", "py-3", "gap-4"]) {
        expect(tokens, `Row must keep ${required}; got ${JSON.stringify(tokens)}`).toContain(required)
      }
    }
    expect(rows[0].textContent).toContain("Cascade depth")
    expect(rows[0].textContent).toContain(CASCADE_ON_TEXT)
    expect(rows[1].textContent).toContain("Timeout budget")
    expect(rows[1].textContent).toContain(TIMEOUT_VALUE)
  })
})

// ---------------------------------------------------------------------------
// B-1: four switches, exact labels, all-on initial state (GREEN)
// ---------------------------------------------------------------------------

describe("B-1: four failover switches render with exact labels, all on", () => {
  it("exactly 4 role=switch controls with exact accessible names, all checked", async () => {
    renderSettings()
    await waitForProviders()
    await openFailover()
    const section = failoverSection()
    const switches = within(section).getAllByRole("switch")
    expect(switches.map((s) => s.getAttribute("aria-label"))).toEqual([
      "Fallback chaining",
      "Failover on rate limit (429)",
      "Failover on timeout",
      "Failover on server error (5xx)",
    ])
    for (const s of switches) {
      expect(s.getAttribute("aria-checked")).toBe("true")
    }
    expect(screen.getByText(CASCADE_ON_TEXT, { exact: true })).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// B-2: master toggle PUTs the exact routing body both ways (GREEN)
// ---------------------------------------------------------------------------

describe("B-2: master Fallback chaining toggle persists the exact routing body", () => {
  it("off-flip PUTs first_only with the honest single-shot copy; on-flip PUTs chained", async () => {
    const user = userEvent.setup()
    const stub = renderSettings()
    await waitForProviders()
    await openFailover()
    const master = screen.getByRole("switch", { name: "Fallback chaining" })

    await user.click(master)
    await waitFor(() => expect(master).toHaveAttribute("aria-checked", "false"))
    expect(screen.getByText(MASTER_OFF_COPY, { exact: true })).toBeInTheDocument()
    expect(screen.getByText(CASCADE_OFF_TEXT, { exact: true })).toBeInTheDocument()

    let puts = routingConfigPuts(stub)
    expect(puts).toHaveLength(1)
    expect(puts[0].body).toEqual({
      fallback_policy: "first_only",
      cost_optimization_preset: "balanced",
      max_attempts: 3,
    })

    await user.click(master)
    await waitFor(() => expect(master).toHaveAttribute("aria-checked", "true"))
    expect(screen.getByText(MASTER_ON_COPY, { exact: true })).toBeInTheDocument()
    expect(screen.getByText(CASCADE_ON_TEXT, { exact: true })).toBeInTheDocument()

    puts = routingConfigPuts(stub)
    expect(puts).toHaveLength(2)
    expect(puts[1].body).toEqual({
      fallback_policy: "chained",
      cost_optimization_preset: "balanced",
      max_attempts: 3,
    })
  })
})

// ---------------------------------------------------------------------------
// B-3: per-condition toggles are session-only — zero PUTs (GREEN)
// ---------------------------------------------------------------------------

describe("B-3: per-condition switches are session-only", () => {
  it("toggling Failover on timeout flips state locally with zero routing PUTs", async () => {
    const user = userEvent.setup()
    const stub = renderSettings()
    await waitForProviders()
    await openFailover()
    expect(routingConfigPuts(stub)).toHaveLength(0)

    const timeoutSwitch = screen.getByRole("switch", { name: "Failover on timeout" })
    await user.click(timeoutSwitch)
    await waitFor(() => expect(timeoutSwitch).toHaveAttribute("aria-checked", "false"))

    expect(routingConfigPuts(stub)).toHaveLength(0)
    expect(screen.getByRole("switch", { name: "Fallback chaining" })).toHaveAttribute(
      "aria-checked",
      "true"
    )
    expect(
      screen.getByRole("switch", { name: "Failover on rate limit (429)" })
    ).toHaveAttribute("aria-checked", "true")
    expect(
      screen.getByRole("switch", { name: "Failover on server error (5xx)" })
    ).toHaveAttribute("aria-checked", "true")
    expect(screen.getByText(CASCADE_ON_TEXT, { exact: true })).toBeInTheDocument()
  })

  it("toggling rate-limit and server-error switches also issues zero routing PUTs", async () => {
    const user = userEvent.setup()
    const stub = renderSettings()
    await waitForProviders()
    await openFailover()

    const rateLimit = screen.getByRole("switch", { name: "Failover on rate limit (429)" })
    const serverError = screen.getByRole("switch", { name: "Failover on server error (5xx)" })
    await user.click(rateLimit)
    await waitFor(() => expect(rateLimit).toHaveAttribute("aria-checked", "false"))
    await user.click(serverError)
    await waitFor(() => expect(serverError).toHaveAttribute("aria-checked", "false"))

    expect(routingConfigPuts(stub)).toHaveLength(0)
    expect(screen.getByText(EXPLAINER_COPY, { exact: true })).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// B-4: keyboard operability (GREEN)
// ---------------------------------------------------------------------------

describe("B-4: all four switches are keyboard-operable", () => {
  it("every switch is an enabled button and Space on the focused master toggles it", async () => {
    const user = userEvent.setup()
    const stub = renderSettings()
    await waitForProviders()
    await openFailover()
    const switches = screen.getAllByRole("switch")
    expect(switches).toHaveLength(4)
    for (const s of switches) {
      expect(s.tagName).toBe("BUTTON")
      expect(s).not.toBeDisabled()
      expect((s as HTMLElement).tabIndex).toBeGreaterThanOrEqual(0)
    }

    const master = screen.getByRole("switch", { name: "Fallback chaining" })
    ;(master as HTMLElement).focus()
    expect(document.activeElement).toBe(master)
    await user.keyboard(" ")
    await waitFor(() => expect(master).toHaveAttribute("aria-checked", "false"))
    const puts = routingConfigPuts(stub)
    expect(puts).toHaveLength(1)
    expect(puts[0].body).toEqual({
      fallback_policy: "first_only",
      cost_optimization_preset: "balanced",
      max_attempts: 3,
    })
  })
})

// ---------------------------------------------------------------------------
// G-1: Providers S-P4 intact (GREEN guard)
// ---------------------------------------------------------------------------

describe("G-1: Providers P1-FINAL merged table (inverted — 7 cols, min-w-960)", () => {
  it("registry section + frame keep w-full max-w-none with overflow-hidden and min-w-[960px] merged table", async () => {
    renderSettings()
    await waitForProviders()
    const table = screen.getByRole("table")
    expect(
      Array.from(table.querySelectorAll("thead th")).map((th) => th.textContent?.trim() ?? "")
    ).toEqual([
      "Priority",
      "Provider",
      "Endpoint",
      "Test",
      "Search",
      "Fetch",
      "Global",
    ])
    const section = table.closest("section") as HTMLElement
    const sectionTokens = classTokens(section)
    expect(sectionTokens).toContain("w-full")
    expect(sectionTokens).toContain("max-w-none")
    expect(cappedMaxWidthTokens(sectionTokens)).toEqual([])
    const container = table.closest('[data-slot="table-container"]') as HTMLElement | null
    expect(container, "ui/table scroller must wrap the provider table").not.toBeNull()
    const frameTokens = classTokens(container!.parentElement as HTMLElement)
    expect(frameTokens).toContain("w-full")
    expect(frameTokens).toContain("max-w-none")
    expect(frameTokens).toContain("overflow-hidden")
    expect(table.className).toMatch(/min-w-\[960px\]/)
    expect(settingsSource).toContain("w-full max-w-none")
  })
})

// ---------------------------------------------------------------------------
// G-2: Keys K1 intact (GREEN guard)
// ---------------------------------------------------------------------------

describe("G-2: Keys K1 stays full-width with a two-column grid", () => {
  it("source keeps w-full max-w-none section plus sm:grid-cols-2 grid", () => {
    expect(keyVaultSource).toMatch(/w-full/)
    expect(keyVaultSource).toMatch(/max-w-none/)
    expect(keyVaultSource).not.toMatch(/max-w-4xl/)
    expect(keyVaultSource).toMatch(/sm:grid-cols-2/)
  })

  it("rendered Keys grid keeps sm:grid-cols-2 inside the full-width section", async () => {
    const user = userEvent.setup()
    renderSettings()
    await waitForProviders()
    await user.click(screen.getByRole("tab", { name: /^Keys$/ }))
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Key vault" })).toBeInTheDocument()
    })
    const heading = screen.getByRole("heading", { name: "Key vault" })
    const section = heading.closest("section") as HTMLElement
    const sectionTokens = classTokens(section)
    expect(sectionTokens).toContain("w-full")
    expect(sectionTokens).toContain("max-w-none")
    const grid = section.querySelector("div.grid") as HTMLElement
    expect(grid, "Keys grid div.grid must exist").not.toBeNull()
    expect(classTokens(grid)).toContain("sm:grid-cols-2")
  })
})

// ---------------------------------------------------------------------------
// G-3: pills intact (GREEN guard)
// ---------------------------------------------------------------------------

describe("G-3: SettingsView pills stay Providers/Keys/Failover", () => {
  it("exactly 3 tabs on the pill variant, no line variant", async () => {
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
})

// ---------------------------------------------------------------------------
// G-4: Carbon Black theme tokens intact (GREEN guard)
// ---------------------------------------------------------------------------

describe("G-4: Carbon Black theme tokens untouched", () => {
  it("#1e1e1e scale + #007acc present, no oklch()", () => {
    expect(norm(indexCssSource).includes("#1e1e1e")).toBe(true)
    expect(norm(indexCssSource).includes("#252526")).toBe(true)
    expect(norm(indexCssSource).includes("#3e3e42")).toBe(true)
    expect(norm(indexCssSource).includes("#007acc")).toBe(true)
    expect(norm(indexCssSource).includes("oklch(")).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// G-5: no merge + freesearch-ui ONLY (GREEN guard)
// ---------------------------------------------------------------------------

describe("G-5: P1-FINAL page merge (inverted — fleet merged, matrix retired)", () => {
  it("Failover never imports sibling sections; shell composition keeps the merged registry", () => {
    expect(failoverSource).not.toMatch(/SettingsProviders/)
    expect(failoverSource).not.toMatch(/SettingsKeyVault/)
    expect(failoverSource).not.toMatch(/ProviderMatrix/)
    expect(failoverSource).not.toMatch(/ProviderTestModal/)
    expect(settingsViewSource).toContain("SettingsProviders")
    expect(settingsViewSource).toContain("SettingsKeyVault")
    expect(settingsViewSource).toContain("SettingsFailover")
    for (const marker of ["Endpoint", "ProviderTestModal"]) {
      expect(settingsFeatureSource, `merged registry must carry ${marker}`).toContain(marker)
    }
  })

  it("Failover imports no backend/python paths and no absolute backend literals", () => {
    expect(failoverSource).not.toMatch(/\.py["']/)
    expect(failoverSource).not.toMatch(/src\/freesearch/)
    expect(failoverSource).not.toMatch(/127\.0\.0\.1:8001/)
    expect(failoverSource).not.toMatch(/localhost:8001/)
  })
})
})

describe("SettingsFailover Developer read-only (canReadControls, no edit)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  function renderDeveloperSettings(): FetchStub {
    const stub = installFetchStub((req) => {
      if (req.url === "/api/v1/providers" && req.method === "GET") {
        return ok(allProvidersFixture())
      }
      if (req.url === "/api/v1/routing/config" && req.method === "GET") {
        return ok(routingConfigFixture())
      }
      if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
      return err(404, { detail: "unhandled test route" })
    })
    render(
      <FreeSearchProvider accountId={DEVELOPER_ACCOUNT_ID} canReadControls canEditControls={false}>
        <SettingsView />
      </FreeSearchProvider>
    )
    return stub
  }

  async function openDeveloperFailover() {
    await waitFor(() => {
      expect(screen.getByText("Brave Search", { exact: true })).toBeInTheDocument()
    })
    await userEvent.setup().click(screen.getByRole("tab", { name: /^Failover$/ }))
    await waitFor(() => {
      expect(screen.getByText("Fallback chaining", { exact: true })).toBeInTheDocument()
    })
  }

  it("shows the read-only policy panel with values, no switches, and sends no writes", async () => {
    const stub = renderDeveloperSettings()
    await openDeveloperFailover()

    // Read-only markers present: four policy rows with the read-only note and stored values.
    expect(screen.getAllByText(/Read-only for your role/)).toHaveLength(4)
    for (const label of [
      "Fallback chaining",
      "Failover on rate limit (429)",
      "Failover on timeout",
      "Failover on server error (5xx)",
    ]) {
      expect(screen.getByText(label, { exact: true })).toBeInTheDocument()
    }
    expect(screen.getByText("Active", { exact: true })).toBeInTheDocument()
    expect(screen.getAllByText("On", { exact: true })).toHaveLength(3)
    expect(screen.getByText("Cascade depth", { exact: true })).toBeInTheDocument()
    expect(screen.getByText("Up to 3 fallback hops", { exact: true })).toBeInTheDocument()
    // Mutation affordances absent: every switch is gone.
    expect(screen.queryByRole("switch")).not.toBeInTheDocument()
    // Zero backend writes beyond the stubbed reads.
    expect(
      stub.requests.filter((r) => r.method === "PATCH" || r.method === "PUT" || r.method === "POST")
    ).toHaveLength(0)
  })
})
