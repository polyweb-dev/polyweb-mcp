Feature: You.com Provider Adapter Integration
  As a search service consumer
  I want to interact with the You.com search provider
  So that I can perform live web searches and fetch web pages

  Background:
    Given a configured and authenticated You.com adapter

  @youcom @live @search
  Scenario: Live search queries You.com and returns structured results
    When I perform a live You.com search for "Python modern async programming" with limit 3
    Then the You.com search response should contain results
    And each You.com search result should have a valid title, url, and snippet

  @youcom @live @fetch
  Scenario: Live fetch extracts clean content from a target URL
    When I perform a live You.com fetch for "https://example.com" with max 2000 chars
    Then the You.com fetch response should contain the target document
    And the You.com document content should be non-empty

  @youcom @live @quota
  Scenario: Live quota reports an estimated remaining search-call balance
    When I query the live You.com quota
    Then the You.com quota snapshot should be an estimate
    And the You.com quota remaining should be a non-negative number
    And the You.com quota should expose no limit or reset
