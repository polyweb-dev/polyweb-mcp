Feature: Brave Provider Adapter Integration
  As a search service consumer
  I want to interact with the Brave Search provider
  So that I can run live web searches and observe normalized results with per-query usage

  Background:
    Given a configured Brave search adapter

  @live @brave
  Scenario: Live Brave search returns normalized results with per-query usage
    When I perform a live Brave search for "python asyncio documentation" with limit 3
    Then the Brave search response should contain normalized results
    And each Brave result should have a non-empty title, snippet, and http(s) URL
    And the Brave usage event should show one search unit

  @live @brave
  Scenario: Brave capabilities and search cost estimate require no network
    When I check the Brave adapter capabilities and search cost estimate
    Then the Brave capabilities should report search and cost estimation without fetch
    And the Brave search cost estimate should be one unit in query currency
