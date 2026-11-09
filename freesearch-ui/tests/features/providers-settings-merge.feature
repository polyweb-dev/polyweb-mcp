@p1final @stub
Feature: Providers settings merge (P1-FINAL)
  The standalone Providers page is retired into System Providers: one table
  carries the registry controls plus the last connection test per row, an
  icon opens the connection-test dialog, and the legacy /providers URL
  redirects to /system/providers. Stat cards, the fleet capability filter and
  the aggregate health counter are dropped.

  Background:
    Given I navigate to the web application

  Scenario: Legacy providers URL redirects into System Providers
    When I navigate directly to "/providers"
    Then the page URL path should be "/system/providers"
    And I should see the "Providers" heading

  Scenario: Sidebar exposes the system administrator links
    Then the sidebar navigation should expose the system administrator links

  Scenario: Provider registry is one table with a per-row Health column
    When I navigate directly to "/system/providers"
    Then the merged provider table should expose headers "Provider, Endpoint, Cost per call, Health, Search, Fetch, Enabled"
    And the merged provider table should show the "api.search.brave.com" endpoint
    And the page should not contain "Provider registry"
    And the page should not contain "Priority dispatch"

  Scenario: Fleet stat cards and capability filter are gone
    When I navigate directly to "/system/providers"
    Then the page should not contain "Total fleet"
    And the page should not contain "Fleet avg latency"
    And the page should not contain "Zero-key tiers"

  Scenario: Icon opens the connection test dialog and Escape closes it
    When I navigate directly to "/system/providers"
    And I open the connection test for "Brave Search"
    Then I should see the connection test dialog for "Brave Search"
    And the connection test dialog should show an endpoint
    And the connection test dialog shows "Last test"
    When I run the connection test
    Then the connection test result shows its age
    When I dismiss the dialog with Escape
    Then the connection test dialog should be closed
