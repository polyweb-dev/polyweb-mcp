/**
 * Provider-commands slice — verbatim extract from ../backendFixtures.ts (step 1).
 */

export function providerTestFixture(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    provider: "brave",
    ok: true,
    status: "healthy",
    latency_ms: 142,
    checked_at: "2026-09-06T10:04:00Z",
    detail: null,
    ...overrides,
  }
}

export function secretStatusFixture(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    provider: "tavily",
    presence: "configured",
    fingerprint: "TAV_••••••••9a1e",
    updated_at: "2026-09-06T10:05:00Z",
    source: "keyring",
    ...overrides,
  }
}

export function breakerResetFixture(provider = "brave"): Record<string, unknown> {
  return {
    provider,
    state: "closed",
    updated_at: "2026-09-06T10:06:00Z",
  }
}
