@stub
Feature: Provider access flags against the stubbed backend
  Settings switches send one-bit PATCH updates for global, search, and fetch
  against deterministic enable and support masks. Brave carries support 3
  (search only); all other providers carry support 7. Stub scenarios prove UI
  wiring only, never real backend enforcement.

  Background:
    Given I navigate to the web application
    When I select the "Settings" header tab
    And I open the "Providers" settings tab

  @stub @access
  Scenario: Successful search PATCH updates the access flag
    When I set the "Keenable" "search" access flag off
    Then the "Keenable" "search" access flag should be off
    When I set the "Keenable" "search" access flag on
    Then the "Keenable" "search" access flag should be on

  @stub @access
  Scenario: Access flag survives reload via backend masks
    When I set the "Tavily" "fetch" access flag off
    Then the "Tavily" "fetch" access flag should be off
    When I reload the page
    And I open the "Providers" settings tab
    Then the "Tavily" "fetch" access flag should be off
    When I set the "Tavily" "fetch" access flag on
    Then the "Tavily" "fetch" access flag should be on

  @stub @access
  Scenario: Search and fetch choices stay independent
    When I set the "Exa" "search" access flag off
    Then the "Exa" "search" access flag should be off
    And the "Exa" "fetch" access flag should be on
    When I set the "Exa" "fetch" access flag off
    Then the "Exa" "fetch" access flag should be off
    And the "Exa" "search" access flag should be off
    When I set the "Exa" "search" access flag on
    Then the "Exa" "search" access flag should be on
    And the "Exa" "fetch" access flag should be off

  @stub @access
  Scenario: Request-active row locks its access flags
    Given the provider PATCH for "Keenable" is delayed by 800 milliseconds
    When I start to set the "Keenable" "search" access flag off without waiting
    Then the "Keenable" "search" access flag should be disabled while pending
    And the "Keenable" "fetch" access flag should be disabled while pending
    And the "Keenable" global access flag should be disabled while pending
    Then the "Keenable" "search" access flag should be off

  @stub @access
  Scenario: Failed PATCH preserves the previous access flag
    Given the provider PATCH for "Keenable" will fail with "stubbed PATCH failure"
    When I set the "Keenable" "search" access flag off
    Then the "Keenable" "search" access flag should be on

  @stub @access
  Scenario: Unsupported tools stay off and unavailable
    Then the "Brave Search" "fetch" access flag should be off and locked as unsupported
    And the "Brave Search" "search" access flag should be on

  @stub @access
  Scenario: Global gate locks tools but preserves raw choices
    When I set the "Keenable" global access flag off
    Then the "Keenable" global access flag should be off
    And the "Keenable" "search" access flag should be disabled while preserving "on"
    And the "Keenable" "fetch" access flag should be disabled while preserving "on"
    When I set the "Keenable" global access flag on
    Then the "Keenable" global access flag should be on
    And the "Keenable" "search" access flag should be on
    And the "Keenable" "fetch" access flag should be on

  @stub @access
  Scenario: Disabled providers leave pickers
    When I set the "Tavily" "fetch" access flag off
    Then the "Tavily" "fetch" access flag should be off
    And the stubbed session works in project Alpha
    When I open the "playground" section of project Alpha
    And I open the playground tab "Fetch"
    Then the "Fetch" operation picker should exclude "Tavily"
