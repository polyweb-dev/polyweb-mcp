Feature: Firecrawl Provider Adapter Integration
  As a search service consumer
  I want to interact with the Firecrawl search provider
  So that I can run a small opt-in live verification of web search and scrape

  # @live scenarios run only when selected explicitly: uv run behave --tags=@live (default_tags excludes @live).

  Background:
    Given a configured Firecrawl key resolved through the shared resolver

  @live @firecrawl @search
  Scenario: Live Firecrawl search returns normalized results
    When a live Firecrawl search runs for "python programming language" with limit 1
    Then the Firecrawl search response should be provider firecrawl
    And each Firecrawl result should have a valid URL
    And the Firecrawl search total should match the result count

  @live @firecrawl @fetch
  Scenario: Live Firecrawl scrape extracts bounded markdown
    When a live Firecrawl scrape fetches "https://example.com" with max 500 chars
    Then the Firecrawl fetch response should contain non-empty markdown
    And the Firecrawl markdown content should be at most 500 chars
