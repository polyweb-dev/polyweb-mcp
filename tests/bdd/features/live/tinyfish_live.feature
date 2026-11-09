@live @tinyfish-live
Feature: Live Tinyfish search and fetch
  As a search service consumer
  I want a live check of the Tinyfish provider adapter
  So that Tinyfish search and fetch are proven against the real vendor like the other providers

  # Manual-only: default_tags excludes @live. Requires FREESEARCH_TINYFISH_API_KEY
  # (or the legacy TINYFISH_API_KEY) in the harness env; skipped without one.

  @search
  Scenario: Live Tinyfish search returns normalized results
    Given a live Tinyfish adapter with a harness key
    When a live Tinyfish search runs for "python programming language" with limit 1
    Then the live Tinyfish search response should be provider tinyfish
    And each live Tinyfish result should have a valid URL
    And the live Tinyfish search total should cover the result count

  @fetch
  Scenario: Live Tinyfish fetch extracts bounded content
    Given a live Tinyfish adapter with a harness key
    When a live Tinyfish fetch runs for "https://example.com" with max 500 chars
    Then the live Tinyfish fetch response should contain non-empty content
    And the live Tinyfish content should be at most 500 chars
