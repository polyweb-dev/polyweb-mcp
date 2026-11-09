@stub @oauth
Feature: Parallel OAuth connects a vault key
  Scenario: An owner connects a Parallel key
    Given the projects backend is stubbed for a system administrator
    When I open Keys and pools
    And I add a Parallel OAuth vault key labelled "Alpha Parallel"
    And I connect the vault key "Alpha Parallel"
    Then the vault OAuth dialog shows the verification code and link
    When Parallel approves vault key "Alpha Parallel"
    Then the vault OAuth dialog shows Connected
