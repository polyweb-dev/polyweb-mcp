Feature: Provider settings workbench
  System Providers is a catalog with the fallback policy under it. Provider
  secrets are managed separately in Account > Keys and pools.

  Background:
    Given I navigate to the web application
    When I navigate directly to "/system/providers"
    Then I should see the "Providers" heading

  @smoke
  Scenario: System Providers has no Keys or Cache tab and the registry has no secret input
    Then the settings page should not expose a "Keys" tab
    And the settings page should not expose a "Cache" tab
    And the settings page should not expose an "Add provider" button
    And the settings page should expose no secret input

  @stub
  Scenario: Provider operation state survives a page reload
    When I view the provider catalog
    And I turn the "Brave Search" "Search" operation off
    Then the "Brave Search" "Search" operation should be off
    When I reload the page
    Then the "Brave Search" "Search" operation should remain off

  @stub
  Scenario: System Providers is a catalog without order controls
    When I view the provider catalog
    Then the provider catalog has no order controls

  @stub
  Scenario: The fallback policy sits under the provider table, with no Failover tab
    When I view the provider catalog
    Then the settings page should not expose a "Failover" tab
    And the failover switch "Fallback" should be visible
    And the failover row "Max attempts" should be visible
    And the failover tab should not show the removed per-condition switches
