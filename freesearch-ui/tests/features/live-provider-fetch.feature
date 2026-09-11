@live
Feature: Live provider fetch smoke coverage
  One live fetch per fetch-capable provider against the real backend
  (no stub). Brave Search has no fetch capability and Exa exposes no
  fetch picker option in this UI revision, so both are skipped here.
  Each scenario captures the FIRST-fetch outcome, retries the same URL,
  and asserts the retry renders content with no API-failure alert.

  Background:
    Given I navigate to the web application
    When I navigate directly to "/playground"

  @live @fetch
  Scenario Outline: Live fetch via <provider> renders content on retry without API failure
    When I open the playground tab "Fetch"
    And I pin the playground fetch provider to "<provider>"
    And I submit the playground fetch URL "https://example.com"
    And I capture the first live fetch outcome for provider "<provider>"
    And I submit the playground fetch URL "https://example.com"
    Then the playground should show live fetch content without an API-failure alert

    Examples:
      | provider  |
      | Keenable  |
      | Tavily    |
      | Firecrawl |
      | You.com   |
      | Parallel  |
