Feature: Exa Provider Adapter Integration
  As a search service consumer
  I want to interact with the Exa search provider
  So that I can perform live web searches and fetch page content

  Background:
    Given a configured and authenticated Exa adapter

  @live @search
  Scenario: Live search queries Exa and returns structured results
    When I perform an Exa live search for "Python modern async programming" with limit 3
    Then the Exa search response should contain results
    And each Exa search result should have a valid title, url, and snippet

  @live @fetch
  Scenario: Live fetch retrieves content for a target URL
    When I perform an Exa live fetch for "https://example.com" with max 2000 chars
    Then the Exa fetch response should contain the target document
    And the Exa document content should be non-empty
