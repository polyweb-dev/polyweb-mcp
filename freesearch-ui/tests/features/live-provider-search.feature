@live
Feature: Live provider search smoke coverage
  One live search per provider against the real backend (no stub).
  Each scenario pins the playground provider, submits a benign query,
  captures the FIRST-search outcome, resubmits the same query, and asserts
  the retry renders results with no API-failure alert. The capture step
  never fails so the first-vs-second pattern is visible per provider. The
  playground is a project section: the run selects the project named by
  FREESEARCH_E2E_PROJECT (default "Local E2E").

  Background:
    Given I navigate to the web application
    When I open the projects list
    And I choose the live e2e project in the project selector
    And I follow the "Playground" link of the Project navigation
    Then I should see the "Search Playground" heading

  @live @search
  Scenario Outline: Live search via <provider> renders results on retry without API failure
    When I pin the playground provider to "<provider>"
    And I submit the playground search query "brief history of the Eiffel Tower"
    And I capture the first live search outcome for provider "<provider>"
    And I submit the playground search query "brief history of the Eiffel Tower"
    Then the playground should show live search results without an API-failure alert

    Examples:
      | provider     |
      | Brave Search |
      | Keenable     |
      | Tavily       |
      | Exa          |
      | Firecrawl    |
      | You.com      |
      | Parallel     |
