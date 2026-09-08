@p1final @stub
Feature: Providers settings merge (P1-FINAL)
  The standalone Providers page is retired into the Settings Providers tab:
  one merged table carries registry controls plus fleet telemetry, an icon
  opens the connection-test modal, and the legacy /providers URL redirects
  to /settings. Stat cards and the fleet capability filter are dropped.

  Background:
    Given I navigate to the web application

  Scenario: Legacy providers URL redirects into Settings
    When I navigate directly to "/providers"
    Then the page URL path should be "/settings"
    And I should see the "Settings" heading
    And I should see the "Provider registry" heading

  Scenario: Sidebar drops the Providers link and exposes five links
    Then the sidebar should not expose a "Providers" link
    And the sidebar navigation should expose five links

  Scenario: Settings registry is one merged table with fleet columns
    When I navigate directly to "/settings"
    Then I should see the "Provider registry" heading
    And the merged provider table should expose headers "Provider, Endpoint, Global, Search, Fetch, Health, p95, Quota, Breaker, Test"
    And the merged provider table should show the "api.search.brave.com" endpoint
    And the merged provider table should show a "Trip" breaker action

  Scenario: Fleet stat cards and capability filter are gone
    When I navigate directly to "/settings"
    Then the page should not contain "Total fleet"
    And the page should not contain "Fleet avg latency"
    And the page should not contain "Zero-key tiers"

  Scenario: Icon opens the connection test dialog and Escape closes it
    When I navigate directly to "/settings"
    And I open the connection test for "Brave Search"
    Then I should see the connection test dialog for "Brave Search"
    And the connection test dialog should show an endpoint
    When I dismiss the dialog with Escape
    Then the connection test dialog should be closed
