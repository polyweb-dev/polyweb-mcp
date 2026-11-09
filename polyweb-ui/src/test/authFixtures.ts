import type {
  BrowserAccessResponse,
  UserAccount,
} from "@/domains/auth/model/types"

/**
 * Safe deterministic account and token fixtures for UI tests.
 *
 * Every UUID is fixed, so snapshots and persistence keys stay stable. No
 * fixture holds a refresh credential: the browser keeps that value in its
 * strict cookie, and tests assert wire bodies instead of seeding storage.
 *
 * An account carries no role. The three personas below differ only by id and
 * email; their authority comes from the system access fixture a test serves
 * (see `accessFixtures.ts`): the admin persona usually pairs with the system
 * administrator permissions, the developer persona with settings read, and the
 * agent persona with no system permission.
 */

/** Account id of the admin persona. */
export const ADMIN_ACCOUNT_ID = "11111111-1111-4111-8111-111111111111"

/** Account id of the developer persona. */
export const DEVELOPER_ACCOUNT_ID = "22222222-2222-4222-8222-222222222222"

/** Account id of the agent persona. */
export const AGENT_ACCOUNT_ID = "33333333-3333-4333-8333-333333333333"

/** Opaque access value for wire bodies. It is not a signed JWT. */
export const TEST_ACCESS_TOKEN = "test-access-token-value"

/** Renewed opaque access value for rotation assertions. */
export const RENEWED_ACCESS_TOKEN = "renewed-access-token-value"

/** Fixture persona: an id and an email prefix, never an authority. */
export type AccountPersona = "admin" | "developer" | "agent"

const FIXTURE_IDS: Record<AccountPersona, string> = {
  admin: ADMIN_ACCOUNT_ID,
  developer: DEVELOPER_ACCOUNT_ID,
  agent: AGENT_ACCOUNT_ID,
}

/** Build one safe account projection, matching the backend `UserAccount` shape. */
export function accountFixture(
  persona: AccountPersona,
  overrides?: Partial<UserAccount>
): UserAccount {
  return {
    id: FIXTURE_IDS[persona],
    email: `${persona}@example.com`,
    auth_provider: "local",
    auth_provider_id: null,
    username: null,
    first_name: null,
    last_name: null,
    is_active: true,
    is_verified: true,
    ...overrides,
  }
}

/** Build the admin persona account. */
export function adminAccountFixture(overrides?: Partial<UserAccount>): UserAccount {
  return accountFixture("admin", overrides)
}

/** Build the developer persona account. */
export function developerAccountFixture(overrides?: Partial<UserAccount>): UserAccount {
  return accountFixture("developer", overrides)
}

/** Build the agent persona account. */
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
