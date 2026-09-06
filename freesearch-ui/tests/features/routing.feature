Feature: Routing workbench
  Routing exposes strategy selection, route simulation, evaluated ranks, and resilience controls.

  Background:
    Given I navigate to the web application
    When I select the "Routing" header tab
    Then I should see the "Routing" heading

  @smoke
  Scenario: Choose a routing strategy and evaluate the lowest latency provider
    Then the routing sub-tabs should be visible: "Strategy", "Simulator", "Ranks", and "Resilience"
    When I choose the "Latency optimized" routing strategy
    Then "Brave Search" is the primary routing provider

  Scenario: Show routing eligibility status as separate text segments
    Then the routing status should show "Failover active"
    And the routing status should show "6 of 7 providers eligible"
    And the routing status should not use a middle-dot separator

  @smoke
  Scenario: Simulate a search route through the execution pipeline
    When I open the "Simulator" routing tab
    And I enter the simulated search query "distributed systems benchmarks"
    And I click the "Simulate route" button
    Then the execution pipeline should contain the "Client Ingress" step
    And the execution pipeline should contain the primary provider "Brave Search"
    And the failover cascade should be rendered

  Scenario: Filter evaluated ranks by operation and provider text
    When I open the "Ranks" routing tab
    And I choose the "Fetch" ranks operation
    Then the ranks table should contain exactly 4 provider rows
    When I choose the "Search" ranks operation
    Then the ranks table should contain exactly 6 provider rows
    And the ranks row for "Brave Search" should show rank "#1" and role "Primary"
    And the ranks row for "Keenable" should show rank "#2" and role "Fallback"
    When I filter the ranks by provider text "Keenable"
    Then the ranks table should contain exactly 1 provider row
    And the filtered ranks row for "Keenable" should show rank "#2" and role "Fallback"

  Scenario: Switch simulator operation from search to fetch
    When I open the "Simulator" routing tab
    And I choose the "Fetch" simulator operation
    Then the simulator input placeholder should be "Type simulated URL..."

  Scenario: Inspect resilience controls
    When I open the "Resilience" routing tab
    Then the resilience row "Cascade depth" should be visible
    And the resilience row "Hop timeout budget" should show "3,000 ms"
    And the resilience row "Circuit breaker auto-bypass" should show "Enabled"
