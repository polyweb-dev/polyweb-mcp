/**
 * Central barrel for test fixtures (step 1: extract + re-export).
 * Every name remains importable from @/test/backendFixtures via the compat shim.
 */

export * from "./providers"
export * from "./routing"
export * from "./dashboard"
export * from "./canonicalDashboard"
export * from "./execution"
export * from "./providerCommands"
