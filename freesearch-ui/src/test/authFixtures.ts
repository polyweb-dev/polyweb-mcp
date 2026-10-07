import type {
  BrowserAccessResponse,
  UserAccount,
  UserRole,
} from "@/domains/auth/model/types"

/**
 * Safe deterministic account and token fixtures for UI tests.
 *
 * Every UUID is fixed, so snapshots and persistence keys stay stable. No
 * fixture holds a refresh credential: the browser keeps that value in its
 * strict cookie, and tests assert wire bodies instead of seeding storage.
 */

/** Confirmed Admin account of the test workspace. */
export const ADMIN_ACCOUNT_ID = "11111111-1111-4111-8111-111111111111"

/** Confirmed Developer account of the test workspace. */
export const DEVELOPER_ACCOUNT_ID = "22222222-2222-4222-8222-222222222222"

/** Confirmed Agent account of the test workspace. */
export const AGENT_ACCOUNT_ID = "33333333-3333-4333-8333-333333333333"

/** Opaque access value for wire bodies. It is not a signed JWT. */
export const TEST_ACCESS_TOKEN = "test-access-token-value"

/** Renewed opaque access value for rotation assertions. */
export const RENEWED_ACCESS_TOKEN = "renewed-access-token-value"

const FIXTURE_IDS: Record<UserRole, string> = {
  admin: ADMIN_ACCOUNT_ID,
  developer: DEVELOPER_ACCOUNT_ID,
  agent: AGENT_ACCOUNT_ID,
}

/** Build one safe account projection for a role. */
export function accountFixture(
  role: UserRole,
  overrides?: Partial<UserAccount>
): UserAccount {
  return {
    id: FIXTURE_IDS[role],
    email: `${role}@example.com`,
    role,
    is_active: true,
    is_superuser: role === "admin",
    is_verified: true,
    ...overrides,
  }
}

/** Build the confirmed Admin account. */
export function adminAccountFixture(overrides?: Partial<UserAccount>): UserAccount {
  return accountFixture("admin", overrides)
}

/** Build the confirmed Developer account. */
export function developerAccountFixture(overrides?: Partial<UserAccount>): UserAccount {
  return accountFixture("developer", overrides)
}

/** Build the confirmed Agent account. */
export function agentAccountFixture(overrides?: Partial<UserAccount>): UserAccount {
  return accountFixture("agent", overrides)
}

/** Build one browser access projection without a refresh credential. */
export function accessResponseFixture(
  overrides?: Partial<BrowserAccessResponse>
): BrowserAccessResponse {
  return {
    access_token: TEST_ACCESS_TOKEN,
    token_type: "bearer",
    expires_in: 900,
    refresh_expires_in: 604800,
    ...overrides,
  }
}
