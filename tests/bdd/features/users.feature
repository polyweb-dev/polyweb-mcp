@users
Feature: Local user accounts, migration, and settings
  As a FreeSearch operator
  I want local accounts, safe migration, and explicit settings
  So that later turns can guard API and MCP tools

  Scenario: Local account creation normalizes email and defaults to Agent
    Given an offline users repository with a temporary database
    When I create a local account with email "Ops@Example.COM"
    Then the stored account should use email "ops@example.com" and role "agent"
    And the stored password hash should verify with the password helper

  Scenario: Provider seam rejects invalid rows and WorkOS cannot use local login
    Given an offline users repository with a temporary database
    When I insert invalid account rows
    Then the database should reject each invalid account row
    And a WorkOS account with a null hash should have no local password hash

  Scenario: Role column defaults to Agent with superuser consistency
    Given an offline users repository with a temporary database
    When I create a local account with email "agent@example.com"
    Then the stored account should use email "agent@example.com" and role "agent"
    And the Agent account should not carry the superuser flag

  Scenario: Migration reaches head 0005 with backup and intact data
    Given a pre-Alembic users database with historical usage rows
    When I run the users database migration
    Then the users database should be at head "0005_tinyfish_plan_label" with a valid schema
    And the historical usage rows should remain unchanged
    And the migration should create the account tables and trace ownership column

  Scenario: Settings require secrets and ports without secret leakage
    Given an offline users repository with a temporary database
    When I check the users settings contracts
    Then a missing signing secret should block authentication
    And settings representations should contain no secret material

  Scenario: Transport composition opens on the migrated database with stub adapters
    Given an offline users API with stub adapters and a temporary database
    When I submit an offline users search
    Then the offline users search should succeed with the stub provider

  Scenario: Registration creates an Agent and login returns a Bearer pair
    Given an offline users API with account auth and stub adapters
    When I register account "auth-bdd@example.com"
    Then the registration should create an Agent account without tokens
    When I log in as the registered account
    Then the login should return a Bearer pair with a 900-second access token
    When I read my account with the access token
    Then the account read should return my record without a hash

  Scenario: Wrong credentials and tokens fail closed
    Given an offline users API with account auth and stub adapters
    When I register account "closed-bdd@example.com"
    Then the registration should create an Agent account without tokens
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
    Then the registration should create an Agent account without tokens
    When I fail login five times and then once more
    Then the sixth login should fail with HTTP 429 and a retry delay

  Scenario: Excess registrations return HTTP 429
    Given an offline users API with account auth and stub adapters
    When I register five accounts and then one more
    Then the sixth registration should fail with HTTP 429 and a retry delay

  Scenario: Refresh rotates once and logout revokes the family
    Given an offline users API with account auth and stub adapters
    When I register account "cycle-bdd@example.com"
    Then the registration should create an Agent account without tokens
    When I log in as the registered account
    Then the login should return a Bearer pair with a 900-second access token
    When I refresh with the refresh token
    Then the refresh should return one successor pair
    When I log out with the successor access token
    Then the logout should revoke the family at once

  Scenario: Consumed-token reuse revokes the whole family
    Given an offline users API with account auth and stub adapters
    When I register account "replay-bdd@example.com"
    Then the registration should create an Agent account without tokens
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
    Then the registration should create an Agent account without tokens
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
      | method | path              |
      | GET    | /stats            |
      | GET    | /dashboard        |
      | GET    | /api/v1/providers |
      | GET    | /api/v1/traces    |
      | GET    | /no-such-route    |

  Scenario: Anonymous Search and Fetch calls are accepted
    Given an offline users API with account auth and stub adapters
    When I call Search and Fetch without a token
    Then both provider operations should succeed

  Scenario: Credentials work only on their own routes
    Given an offline users API with account auth and stub adapters
    When I register account "separate-bdd@example.com"
    Then the registration should create an Agent account without tokens
    When I log in as the registered account
    Then the login should return a Bearer pair with a 900-second access token
    When I use the refresh token on search and the access token on refresh
    Then both misplaced credentials should fail with HTTP 401

  Scenario: Provider controls follow the Admin Developer Agent matrix
    Given an offline users API with account auth and stub adapters
    When I prepare Admin, Developer, and Agent accounts
    Then anonymous control calls should fail with HTTP 401
    And provider reads should allow Admin and Developer but deny Agent
    And provider mutations should allow Admin but deny Developer and Agent
    And Agent search should succeed

  Scenario: Browser login issues a strict cookie without a JSON refresh credential
    Given an offline users API with browser cookie transport
    When I register account "browser-bdd@example.com"
    Then the registration should create an Agent account without tokens
    When I log in through the browser
    Then the browser login should issue a strict cookie without a JSON refresh credential

  Scenario: Non-browser clients keep JSON pairs without cookies
    Given an offline users API with browser cookie transport
    When I register account "programmatic-bdd@example.com"
    Then the registration should create an Agent account without tokens
    When I log in as the registered account
    Then the login should return a Bearer pair with a 900-second access token
    And the programmatic login should set no cookie

  Scenario: Browser refresh rotates the cookie and reuse revokes the family
    Given an offline users API with browser cookie transport
    When I register account "browser-rotate-bdd@example.com"
    Then the registration should create an Agent account without tokens
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
    Then the registration should create an Agent account without tokens
    When I log in through the browser
    Then the browser login should issue a strict cookie without a JSON refresh credential
    When I refresh with an invalid Origin
    Then the invalid Origin refresh should fail with HTTP 403 without cookie deletion
    When I log out through the browser cookie
    Then the browser logout should revoke the family and expire the cookie

  Scenario: Each role signs up and logs in with its own role
    Given an offline users API with account auth and stub adapters
    When I register with role "admin" as "t2-admin-bdd@example.com"
    Then the role signup should create "admin" without tokens
    When I register with role "developer" as "t2-developer-bdd@example.com"
    Then the role signup should create "developer" without tokens
    When I register with role "agent" as "t2-agent-bdd@example.com"
    Then the role signup should create "agent" without tokens
    When I log in with role "admin" as "t2-admin-bdd@example.com"
    Then the role login should report "admin" with a 900-second access token

  Scenario: Old callers omit the role and still create Agent
    Given an offline users API with account auth and stub adapters
    When I register account "t2-omitted-bdd@example.com"
    Then the registration should create an Agent account without tokens

  Scenario: Admin creates each role without project association
    Given an offline users API with account auth and stub adapters
    When I prepare Admin, Developer, and Agent accounts
    And the Admin provisions an "admin" account
    Then the provisioning should create "admin" without credentials and keep the caller live
    When the Admin provisions a "developer" account
    Then the provisioning should create "developer" without credentials and keep the caller live
    When the Admin provisions an "agent" account
    Then the provisioning should create "agent" without credentials and keep the caller live

  Scenario: Other roles cannot provision accounts
    Given an offline users API with account auth and stub adapters
    When I prepare Admin, Developer, and Agent accounts
    Then a Developer provisioning should fail with HTTP 403
    And an Agent provisioning should fail with HTTP 403
    And an anonymous provisioning should fail with HTTP 401

  Scenario: Legacy account lookup and role change deny every caller
    Given an offline users API with account auth and stub adapters
    When I prepare Admin, Developer, and Agent accounts
    Then legacy account routes should deny every role with HTTP 403 and keep sessions live

  Scenario: Public and provisioning creation share one limit
    Given an offline users API with account auth and stub adapters
    When I prepare one Admin account
    And I consume the shared creation limit
    Then the sixth creation should fail with HTTP 429 and a retry delay

  Scenario: Creation input stays safe
    Given an offline users API with account auth and stub adapters
    When I prepare one Admin account
    Then invalid creation roles should fail with safe HTTP 422
    And privileged creation fields should fail with safe HTTP 422
    And weak provisioned passwords and duplicate email should fail safely
