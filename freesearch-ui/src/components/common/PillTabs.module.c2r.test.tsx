import { describe, it, expect } from "vitest"

/**
 * C2-REWORK AC-C2R-1 (RED): the plan requires a NEW reusable
 * `shared/ui/PillTabs.tsx` (provider-page pill look with tab semantics:
 * tablist/tab/tabpanel, aria-selected, linkage, keyboard) consumed by
 * SearchPlayground, RoutingEngine, and SettingsView.
 *
 * Red expectation: this file fails to resolve `@/shared/ui/PillTabs` (the
 * module does not exist yet), which is the clean non-vacuous proof. It goes
 * green once the Developer creates the module; per-page pill behavior is
 * pinned by `PillTabs.c2r.test.tsx`. (CLEANUP 1.1: the `common/PillTabs`
 * compat shell was removed; the canonical module lives in shared/ui.)
 */
describe("C2-REWORK AC-C2R-1: reusable PillTabs module exists", () => {
  it("shared/ui/PillTabs exposes a reusable view-switcher component", async () => {
    const mod = (await import("@/shared/ui/PillTabs").catch(() => null)) as null | {
      PillTabs?: unknown
      default?: unknown
    }
    expect(mod, "shared/ui/PillTabs module must exist").not.toBeNull()
    const PillTabs =
      (mod as { PillTabs?: unknown }).PillTabs ??
      (mod as { default?: unknown }).default
    expect(typeof PillTabs, "PillTabs must be a component").toBe("function")
  })
})
