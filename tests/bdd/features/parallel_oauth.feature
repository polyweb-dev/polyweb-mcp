@control @oauth
Feature: Parallel OAuth device flow and Account API balance
  As a local FreeSearch operator
  I want to pair Parallel through a browser device flow
  So that the dashboard shows an AUTHORITATIVE USD balance without API keys

  Scenario: Device flow initiation returns the public code pair only
    Given an offline Parallel OAuth API with stubbed platform responses
    When I start the Parallel device flow
    Then the device code response should carry the user code and verification URIs
    And the device code response should contain no token or device secret

  Scenario: Approved device flow becomes ready through bounded polls
    Given an offline Parallel OAuth API with a pending device flow
    When I check the Parallel OAuth status
    Then the OAuth status should be pending with a positive expiry
    When the stubbed user approves the device code
    And the poll interval elapses
    And I check the Parallel OAuth status
    Then the OAuth status should be ready
    And each status check should have attempted at most one token call

  Scenario: Rapid status checks honor the poll interval
    Given an offline Parallel OAuth API with a pending device flow
    When I check the Parallel OAuth status twice in quick succession
    Then the OAuth status should be pending with a positive expiry
    And the token endpoint should have been called exactly once

  Scenario: Denied device flow is terminal without further polling
    Given an offline Parallel OAuth API with a pending device flow
    When the stubbed user denies the device code
    And I check the Parallel OAuth status
    Then the OAuth status should be denied
    When I check the Parallel OAuth status again
    Then the OAuth status should still be denied with no extra token call

  Scenario: Expired device flow reports expired
    Given an offline Parallel OAuth API with an expired device code
    When I check the Parallel OAuth status
    Then the OAuth status should be expired

  Scenario: Balance cents map to an AUTHORITATIVE USD snapshot
    Given an offline Parallel OAuth API with a paired bearer
    When the bounded quota poll runs with credit 1250 cents and pending 250 cents
    Then the Parallel latest quota should be AUTHORITATIVE USD 10.00 with unknown limit

  Scenario Outline: Invoice-billed and overdrawn balances stay honest
    Given an offline Parallel OAuth API with a paired bearer
    When the bounded quota poll runs with credit <credit> cents and pending <pending> cents invoiced <invoiced>
    Then the Parallel balance outcome should be "<outcome>"

    Examples:
      | credit | pending | invoiced | outcome       |
      | 1250   | 250     | false    | USD 10.00     |
      | 100    | 500     | false    | USD 0.00      |
      | 9999   | 0       | true     | missing       |

  Scenario: Balance rejection unpairs and backs off without hot-looping
    Given an offline Parallel OAuth API with a paired bearer
    When the bounded quota poll runs with a rejected bearer
    Then the OAuth status should be unpaired
    When the bounded quota poll runs again immediately
    Then no extra balance call should have been made

  Scenario: Disconnect revokes before deleting and stays idempotent
    Given an offline Parallel OAuth API with a paired bearer
    When I disconnect the Parallel OAuth pairing
    Then the revocation should precede the deletion and the status should be unpaired
    When I disconnect the Parallel OAuth pairing again
    Then the disconnect should still return 204

  Scenario: Starting a second device flow while paired returns conflict
    Given an offline Parallel OAuth API with a paired bearer
    When I start the Parallel device flow again
    Then the device flow should conflict with 409 and the bearer should survive

  Scenario: Other providers reject OAuth pairing
    Given an offline Parallel OAuth API with stubbed platform responses
    When I start the device flow for "exa"
    Then the OAuth response should be 404 oauth-not-supported
    When I check the OAuth status for "ghost"
    Then the OAuth response should be 404 unknown provider
