/**
 * Compat re-export shim (step 1: Slice 3 tail-C).
 *
 * Canonical implementations live in ./fixtures/* (verbatim extracts).
 * Existing suites keep importing from "@/test/backendFixtures" with zero changes.
 * Do NOT add logic here — re-export only.
 */

export * from "./fixtures/providers"
export * from "./fixtures/routing"
export * from "./fixtures/dashboard"
export * from "./fixtures/canonicalDashboard"
export * from "./fixtures/execution"
export * from "./fixtures/providerCommands"
