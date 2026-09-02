Feature: Keenable Provider Adapter Integration
  As a search service consumer
  I want to interact with the Keenable search provider
  So that I can perform free, keyless live web searches with zero-unit usage

  @live @keenable @search
  Scenario: Live keyless search queries Keenable and returns structured results
    Given the Keenable adapter is ready for keyless search
    When I perform a live Keenable search for "Python" with limit 1
    Then the Keenable search response should use provider "keenable"
    And the Keenable search response should contain at least one valid result
    And the Keenable search response should report correct total count
    And the Keenable search response should report zero-unit usage
    And the live Keenable request should use the keyless public endpoint
