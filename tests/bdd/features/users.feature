@users
Feature: Local user accounts, migration, and settings
  As a Polyweb operator
  I want local accounts, safe migration, and explicit settings
  So that later turns can guard API and MCP tools

  Scenario: Local account creation normalizes email and creates an ordinary account
    Given an offline users repository with a temporary database
    When I create a local account with email "Ops@Example.COM"
    Then the stored account should use email "ops@example.com" and hold no system role
    And the stored password hash should verify with the password helper

  Scenario: Provider seam rejects invalid rows and WorkOS cannot use local login
    Given an offline users repository with a temporary database
    When I insert invalid account rows
    Then the database should reject each invalid account row
    And a WorkOS account with a null hash should have no local password hash

  Scenario: A new account holds no system role and no superuser flag
    Given an offline users repository with a temporary database
    When I create a local account with email "agent@example.com"
    Then the stored account should use email "agent@example.com" and hold no system role
    And the ordinary account should not carry the superuser flag

  Scenario: A pre-alpha users database is refused with a reset message and intact data
    Given a pre-Alembic users database with historical usage rows
    When I run the users database migration
    Then the users database migration should be refused with a reset message
    And the historical usage rows should remain unchanged
    And the refused users database should have no account tables

  Scenario: Settings require secrets and ports without secret leakage
    Given an offline users repository with a temporary database
    When I check the users settings contracts
    Then a missing signing secret should block authentication
    And settings representations should contain no secret material

  Scenario: Transport composition opens on the migrated database with stub adapters
    Given an offline users API with stub adapters and a temporary database
    When I submit an offline users search
    Then the offline users search should succeed with the stub provider

  Scenario: Registration creates an ordinary account and login returns a Bearer pair
    Given an offline users API with account auth and stub adapters
    When I register account "auth-bdd@example.com"
    Then the registration should create an ordinary account without tokens
    When I log in as the registered account
    Then the login should return a Bearer pair with a 900-second access token
    When I read my account with the access token
    Then the account read should return my record without a hash

  Scenario: Wrong credentials and tokens fail closed
    Given an offline users API with account auth and stub adapters
    When I register account "closed-bdd@example.com"
    Then the registration should create an ordinary account without tokens
    When I log in with a wrong password
    Then the login should fail with bad credentials
    When I read my account without a token
    Then the account read should fail with HTTP 401
    When I read my account with a malformed token
    Then the account read should fail with HTTP 401

  Scenario Outline: Weak passwords cannot create accounts
    Given an offline users API with account auth and stub adapters
    When I register with weak password "<password>"
    Then the registration should fail with the password rule

    Examples:
      | password          |
      | short1!A          |
      | alllowercase123!  |
      | ALLUPPERCASE123!  |
      | NoSpecial123Aax   |

  Scenario: Repeated failed logins return HTTP 429
    Given an offline users API with account auth and stub adapters
    When I register account "limit-bdd@example.com"
    Then the registration should create an ordinary account without tokens
    When I fail login five times and then once more
    Then the sixth login should fail with HTTP 429 and a retry delay

  Scenario: Excess registrations return HTTP 429
    Given an offline users API with account auth and stub adapters
    When I register five accounts and then one more
    Then the sixth registration should fail with HTTP 429 and a retry delay

  Scenario: Refresh rotates once and logout revokes the family
    Given an offline users API with account auth and stub adapters
    When I register account "cycle-bdd@example.com"
    Then the registration should create an ordinary account without tokens
    When I log in as the registered account
    Then the login should return a Bearer pair with a 900-second access token
    When I refresh with the refresh token
    Then the refresh should return one successor pair
    When I log out with the successor access token
    Then the logout should revoke the family at once

  Scenario: Consumed-token reuse revokes the whole family
    Given an offline users API with account auth and stub adapters
    When I register account "replay-bdd@example.com"
    Then the registration should create an ordinary account without tokens
    When I log in as the registered account
    Then the login should return a Bearer pair with a 900-second access token
    When I refresh with the refresh token
    Then the refresh should return one successor pair
    When I reuse the consumed refresh token
    Then the reuse should fail with HTTP 401
    And the successor credentials should fail at once

  Scenario: Successful login clears only the pair limit
    Given an offline users API with account auth and stub adapters
    When I register account "pair-clear-bdd@example.com"
    Then the registration should create an ordinary account without tokens
    When I fail login four times
    And I log in as the registered account
    Then the login should return a Bearer pair with a 900-second access token
    When I fail login five times and then once more
    Then the sixth login should fail with HTTP 429 and a retry delay

  Scenario: Oversize public auth bodies return HTTP 413
    Given an offline users API with account auth and stub adapters
    When I register with a 4097-byte body
    Then the oversize auth call should fail with HTTP 413 and no credential content
    When I log in with a 4097-byte body
    Then the oversize auth call should fail with HTTP 413 and no credential content

  Scenario Outline: Anonymous calls cannot reach protected surfaces
    Given an offline users API with account auth and stub adapters
    When I call "<method> <path>" without a token
    Then the call should fail with HTTP 401 and a Bearer challenge

    Examples:
      | method | path                                                         |
      | GET    | /stats                                                       |
      | GET    | /dashboard                                                   |
      | GET    | /api/v1/providers                                            |
      | GET    | /api/v1/projects/00000000-0000-4000-8000-0000000000aa/traces     |
      | GET    | /no-such-route                                               |

  Scenario: Anonymous Search and Fetch calls are rejected
    Given an offline users API with account auth and stub adapters
    When I call Search and Fetch without a token
    Then both provider operations should be rejected with 401

  Scenario: Credentials work only on their own routes
    Given an offline users API with account auth and stub adapters
    When I register account "separate-bdd@example.com"
    Then the registration should create an ordinary account without tokens
    When I log in as the registered account
    Then the login should return a Bearer pair with a 900-second access token
    When I use the refresh token on search and the access token on refresh
    Then both misplaced credentials should fail with HTTP 401

  Scenario: Provider controls follow scoped system and project authority
    Given an offline users API with account auth and stub adapters
    And a Brave stub for the scoped authority scenario
    When I prepare system admin, project admin, and member accounts
    And the member has search permission and the project has a Brave pool
    Then anonymous control calls should fail with HTTP 401
    And provider reads should allow only the system admin
    And provider mutations should allow only the system admin
    And the member should search the pooled project but the system admin should not

  Scenario: Browser login issues a strict cookie without a JSON refresh credential
    Given an offline users API with browser cookie transport
    When I register account "browser-bdd@example.com"
    Then the registration should create an ordinary account without tokens
    When I log in through the browser
    Then the browser login should issue a strict cookie without a JSON refresh credential

  Scenario: Non-browser clients keep JSON pairs without cookies
    Given an offline users API with browser cookie transport
    When I register account "programmatic-bdd@example.com"
    Then the registration should create an ordinary account without tokens
    When I log in as the registered account
    Then the login should return a Bearer pair with a 900-second access token
    And the programmatic login should set no cookie

  Scenario: Browser refresh rotates the cookie and reuse revokes the family
    Given an offline users API with browser cookie transport
    When I register account "browser-rotate-bdd@example.com"
    Then the registration should create an ordinary account without tokens
    When I log in through the browser
    Then the browser login should issue a strict cookie without a JSON refresh credential
    When I refresh through the browser cookie
    Then the browser refresh should rotate the cookie once
    When I reuse the consumed browser cookie
    Then the consumed browser reuse should fail with HTTP 401 and expire the cookie
    And the rotated browser credentials should fail at once

  Scenario: Browser logout deletes the cookie and invalid Origin keeps the family
    Given an offline users API with browser cookie transport
    When I register account "browser-logout-bdd@example.com"
    Then the registration should create an ordinary account without tokens
    When I log in through the browser
    Then the browser login should issue a strict cookie without a JSON refresh credential
    When I refresh with an invalid Origin
    Then the invalid Origin refresh should fail with HTTP 403 without cookie deletion
    When I log out through the browser cookie
    Then the browser logout should revoke the family and expire the cookie

  Scenario: Signup cannot request a role
    Given an offline users API with account auth and stub adapters
    When I register with role "admin" as "t2-admin-bdd@example.com"
    Then the role signup should be refused with HTTP 422
    When I register with role "developer" as "t2-developer-bdd@example.com"
    Then the role signup should be refused with HTTP 422
    When I register with role "agent" as "t2-agent-bdd@example.com"
    Then the role signup should be refused with HTTP 422

  Scenario: Signup without a role creates an ordinary account
    Given an offline users API with account auth and stub adapters
    When I register account "t2-omitted-bdd@example.com"
    Then the registration should create an ordinary account without tokens
