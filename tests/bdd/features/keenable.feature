Feature: Keenable Provider Adapter Integration
  As a search service consumer
  I want to interact with the Keenable search provider
  So that I can perform free, keyless live web searches while tracking hourly request usage

  # @live scenarios run only when selected explicitly: uv run behave --tags=@live (default_tags excludes @live).

  @live @keenable @search
  Scenario: Live keyless search queries Keenable and returns structured results
    Given the Keenable adapter is ready for keyless search
    When I perform a live Keenable search for "open data documentation" with limit 1
    Then the Keenable search response should use provider "keenable"
    And the Keenable search response should contain at least one valid result
    And the Keenable search response should report correct total count
    And the Keenable search response should report one request unit
    And the live Keenable request should use the keyless public endpoint

  @live @keenable @fetch
  Scenario: Live keyless fetch extracts content with one request unit
    Given the Keenable adapter is ready for keyless search
    When I perform a live Keenable fetch for "https://example.com" with max 1000 chars
    Then the Keenable fetch response should contain non-empty content within 1000 chars
    And the Keenable fetch response should report one request unit
    And the live Keenable fetch should use the keyless public endpoint

  @live @keenable @keenable-keyed @search
  Scenario: Live keyed search requires a Keenable API key
    Given the Keenable adapter is ready for keyed search
    When I perform a live Keenable search for "open data documentation" with limit 1
    Then the Keenable search response should use provider "keenable"
    And the Keenable search response should report correct total count
