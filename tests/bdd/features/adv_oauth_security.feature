@control @adv-oauth @oauth-security
Feature: Parallel OAuth token confinement
  As a FreeSearch operator
  I want bearer tokens confined to the encrypted vault
  So that logs, responses, and database rows stay fingerprint-only

  Background:
    Given an offline Parallel OAuth API with stubbed vendor

  Scenario: Error paths leak no token material
    When I drive every OAuth error path
    Then no log record or response body should contain token material

  Scenario: Vault holds the bearer while the database holds none
    Given a connected Parallel OAuth session
    Then the vault should hold the bearer while the database holds none

  Scenario: Status stays fingerprint-only
    Given a connected Parallel OAuth session
    When I read OAuth status for "parallel"
    Then the status should be fingerprint-only
