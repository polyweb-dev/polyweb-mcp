@live
Feature: Live provider fetch smoke coverage
  One live fetch per fetch-capable provider against the real backend
  (no stub). Brave Search has no fetch capability so it is skipped here.
  Each scenario captures the FIRST-fetch outcome, retries the same URL,
  and asserts the retry renders content with no API-failure alert. The
  playground is a project section: the run selects the project named by
  FREESEARCH_E2E_PROJECT (default "Local E2E").

  Background:
    Given I navigate to the web application
    When I open the projects list
    And I choose the live e2e project in the project selector
    And I follow the "Playground" link of the Project navigation
    Then I should see the "Playground" heading

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
      | Exa       |
      | Firecrawl |
      | You.com   |
      | Parallel  |
