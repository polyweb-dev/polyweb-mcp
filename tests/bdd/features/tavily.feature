Feature: Tavily Provider Adapter Integration
  As a search service consumer
  I want to interact with the Tavily search provider
  So that I can perform live web searches, fetch web pages, and monitor my credit quota

  # @live scenarios run only when selected explicitly: uv run behave --tags=@live (default_tags excludes @live).

  Background:
    Given a configured and authenticated Tavily adapter

  @live @search
  Scenario: Live search queries Tavily and returns structured results
    When I perform a live search for "Python modern async programming" with limit 3
    Then the search response should contain results
    And each search result should have a valid title, url, and snippet
    And the search response should report observed usage credits

  @live @fetch
  Scenario: Live fetch extracts clean content from a target URL
    When I perform a live fetch for "https://example.com" with max 2000 chars
    Then the fetch response should contain the target document
    And the document content should be non-empty
    And the fetch response should report observed usage credits

  @live @quota
  Scenario: Live quota query retrieves authoritative remaining credits
    When I request the current Tavily quota snapshot
    Then the quota snapshot should be authoritative
    And the remaining credits should be a non-negative number
    And the quota limit should be greater than zero
