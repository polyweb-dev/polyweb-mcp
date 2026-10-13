Feature: Routing workbench
  Routing exposes strategy selection and route simulation.
  Against the live backend all counts are backend-tolerant: the suite asserts
  shapes and regex ranges, never exact provider totals.

  Background:
    Given I navigate to the web application
    When I select the "Routing" header tab
    Then I should see the "Routing" heading

  @smoke @stub
  Scenario: Choose a routing strategy and evaluate the lowest latency provider
    Then the routing sub-tabs should be visible: "Strategy" and "Simulator"
    When I choose the "Latency optimized" routing strategy
    Then a primary routing provider row should be visible

  @smoke @stub
  Scenario: Simulate a search route through the execution pipeline
    When I open the "Simulator" routing tab
    And I enter the simulated search query "distributed systems benchmarks"
    And I click the "Simulate route" button
    Then the execution pipeline should contain the "Client Ingress" step
    And the execution pipeline should contain a primary provider
    And the failover cascade should be rendered

  @stub
  Scenario: Switch simulator operation from search to fetch
    When I open the "Simulator" routing tab
    And I choose the "Fetch" simulator operation
    Then the simulator input placeholder should be "Type simulated URL..."

  @smoke
  Scenario: Submit a playground search against the live backend
    When I select the "Playground" header tab
    And I submit the playground search query "distributed systems benchmarks"
    Then the playground should show search results or an error banner
    And the playground should not show multi-hop fallback text
