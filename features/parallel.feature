Feature: Parallel Provider Adapter Integration
  As a search service consumer
  I want to interact with the Parallel search provider
  So that I can perform live web searches and fetch web pages

  Background:
    Given a configured Parallel adapter

  @live @parallel @search
  Scenario: Live search queries Parallel and returns structured results
    When I perform a live Parallel search for "Python modern async programming" with limit 1
    Then the Parallel search response should contain structured results
    And the Parallel search response should report a non-negative usage event with a request id

  @live @parallel @fetch
  Scenario: Live fetch extracts clean content from a target URL
    When I perform a live Parallel fetch for "https://example.com" with max 1000 chars
    Then the Parallel fetch response should contain the target document
    And the document content should be non-empty and obey the max char limit
    And the Parallel fetch response should report a non-negative usage event with a request id
