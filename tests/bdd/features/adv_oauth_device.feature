@control @adv-oauth @oauth-device
Feature: Parallel OAuth device flow contract
  As a FreeSearch operator
  I want the Parallel device flow to follow the frozen OAuth shape
  So that account linking is strict, scoped, and leak-free

  Background:
    Given an offline Parallel OAuth API with stubbed vendor

  Scenario: Device code returns the strict contract shape
    When I request a device code for "parallel"
    Then the device code response should carry the strict contract shape
    And the device code response should contain no token fields

  Scenario: Smuggled input never surfaces
    When I request a device code with an extra smuggled field
    Then the smuggled value should never surface

  Scenario Outline: Only parallel supports OAuth
    When I create a vault OAuth key for "<provider>"
    Then the vault should reject the unsupported OAuth provider without vendor calls

    Examples:
      | provider  |
      | exa       |
      | tavily    |
      | firecrawl |
      | you       |
      | brave     |
      | keenable  |

  Scenario Outline: Device poll edges surface terminal states
    Given a stubbed "<outcome>" device poll outcome
    When I start the device flow and poll status to terminal
    Then the OAuth status should become "<status>"

    Examples:
      | outcome       | status  |
      | access_denied | denied  |
      | expired_token | expired |
