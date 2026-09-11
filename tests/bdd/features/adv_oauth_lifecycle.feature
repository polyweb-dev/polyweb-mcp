@control @adv-oauth @oauth-lifecycle
Feature: Parallel OAuth lifecycle and resilience
  As a FreeSearch operator
  I want disconnect and failure handling to be ordered and bounded
  So that revocation, idempotency, and dead grants never herd or leak

  Background:
    Given an offline Parallel OAuth API with stubbed vendor

  Scenario: Disconnect revokes before deleting the vault key
    Given a connected Parallel OAuth session
    When I disconnect OAuth for "parallel"
    Then the disconnect should be accepted with revoke before vault delete

  Scenario: Disconnect stays idempotent
    Given a connected Parallel OAuth session
    When I disconnect OAuth for "parallel" twice
    Then both disconnects should be accepted and status should be unpaired

  Scenario: Dead grants settle to unpaired without a hot loop
    Given a connected Parallel OAuth session with a poisoned grant
    When I read OAuth status repeatedly
    Then the OAuth status should be unpaired without a vendor hot-loop

  Scenario: Slow-down and interval are honored
    Given a stubbed slow_down device poll script with interval 5
    When I start the device flow and poll status rapidly
    Then the flow should reach ready with bounded vendor polls
