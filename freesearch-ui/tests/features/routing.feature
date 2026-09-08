Feature: Routing workbench
  Routing exposes strategy selection, route simulation, evaluated ranks, and resilience controls.
  Against the live backend all counts are backend-tolerant: the suite asserts
  shapes and regex ranges, never exact provider totals.

  Background:
    Given I navigate to the web application
    When I select the "Routing" header tab
    Then I should see the "Routing" heading

  @smoke @stub
  Scenario: Choose a routing strategy and evaluate the lowest latency provider
    Then the routing sub-tabs should be visible: "Strategy", "Simulator", "Ranks", and "Resilience"
    When I choose the "Latency optimized" routing strategy
    Then a primary routing provider row should be visible

  @stub
  Scenario: Show routing eligibility status as separate text segments
    Then the routing status should show "Failover active"
    # R1 StatusBar contract: the bar trigger reads "N of M providers" (no
    # "eligible" word, no middle-dot separator) — separate text segments.
    And the routing eligibility should match "\d+ of \d+ providers"
    And the routing status should not use a middle-dot separator

  @smoke @stub
  Scenario: Simulate a search route through the execution pipeline
    When I open the "Simulator" routing tab
    And I enter the simulated search query "distributed systems benchmarks"
    And I click the "Simulate route" button
    Then the execution pipeline should contain the "Client Ingress" step
    And the execution pipeline should contain a primary provider
    And the failover cascade should be rendered

  @stub
  Scenario: Filter evaluated ranks by operation and provider text
    When I open the "Ranks" routing tab
    And I choose the "Fetch" ranks operation
    Then the ranks table should contain at least 1 provider row
    When I choose the "Search" ranks operation
    Then the ranks table should contain at least 1 provider row
    And the first ranks row should show role "Primary"
    When I filter the ranks by provider text "Keenable"
    Then the ranks table should contain exactly 1 provider row

  @stub
  Scenario: Switch simulator operation from search to fetch
    When I open the "Simulator" routing tab
    And I choose the "Fetch" simulator operation
    Then the simulator input placeholder should be "Type simulated URL..."

  @stub
  Scenario: Inspect resilience controls
    When I open the "Resilience" routing tab
    Then the resilience row "Cascade depth" should be visible
    And the resilience row "Hop timeout budget" should not show "3,000 ms"

  @smoke
  Scenario: Submit a playground search against the live backend
    When I select the "Playground" header tab
    And I submit the playground search query "distributed systems benchmarks"
    Then the playground should show search results or an error banner
    And the playground should not show multi-hop fallback text
