/**
 * Routing slice — verbatim extract from ../backendFixtures.ts (step 1).
 */

export function routingConfigFixture(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    fallback_policy: "chained",
    max_attempts: 3,
    ...overrides,
  }
}
