Feature: Provider settings workbench
  The global "Provider settings" page separates provider routing controls and
  failover policy. It writes no provider secret: system credentials live on
  the System credentials page and project keys on each project's Providers
  page (system-credentials.feature, project-providers.feature), where the
  write-only secret assertions of the former Keys tab now live.

  Background:
    Given I navigate to the web application
    When I select the "Provider settings" header tab
    Then I should see the "Settings" heading

  @smoke
  Scenario: Provider settings has only provider and failover tabs and no secret input
    Then the settings page should expose exactly 2 sub-tabs
    And the settings page should not expose a "Keys" tab
    And the settings page should not expose a "Cache" tab
    And the settings page should not expose an "Add provider" button
    And the settings page should expose no secret input

  @stub
  Scenario: Provider operation state survives switching settings tabs
    When I open the "Providers" settings tab
    And I turn the "Brave Search" "Search" operation off
    Then the "Brave Search" "Search" operation should be off
    When I open the "Failover" settings tab
    And I open the "Providers" settings tab
    Then the "Brave Search" "Search" operation should remain off

  @stub
  Scenario: Provider priority arrows stop at registry boundaries
    When I open the "Providers" settings tab
    Then the first provider row upward priority arrow should be disabled
    And the last provider row downward priority arrow should be disabled

  @stub
  Scenario: Failover policy exposes a vertical switch stack with descriptions
    When I open the "Failover" settings tab
    Then the failover switch "Fallback chaining" should be visible
    And the failover switch "Failover on rate limit (429)" should be visible
    And the failover switch "Failover on timeout" should be visible
    And the failover switch "Failover on server error (5xx)" should be visible
    And each failover switch should expose a description
    And the failover operation switches should be vertically stacked
    And the failover row "Cascade depth" should be visible
    And the failover row "Timeout budget" should be visible
