@stub
Feature: Provider search and fetch against the stubbed backend
  Pinned provider search and fetch go through deterministic /search and
  /fetch stubs from the project playground; the picker lists the providers
  whose project effective operations include the mode. Search asserts results-or-error; fetch asserts
  content-or-error — except Brave fetch, which has no fetch capability and
  must be absent from the fetch picker.

  Background:
    Given the stubbed session works in project Alpha
    When I open the "playground" section of project Alpha

  @stub @brave @search
  Scenario: Brave pinned search returns stubbed results or an honest error
    When I pin the playground provider to "Brave Search"
    And I submit the playground search query "open data documentation"
    Then the playground should show search results or an error banner

  @stub @brave @fetch
  Scenario: Brave has no fetch capability in the fetch picker
    When I open the playground tab "Fetch"
    Then the fetch provider picker should not offer "Brave Search"

  @stub @parallel @search
  Scenario: Parallel pinned search returns stubbed results or an honest error
    When I pin the playground provider to "Parallel"
    And I submit the playground search query "open data documentation"
    Then the playground should show search results or an error banner

  @stub @parallel @fetch
  Scenario: Parallel pinned fetch returns stubbed content or an honest error
    When I open the playground tab "Fetch"
    And I pin the playground fetch provider to "Parallel"
    And I submit the playground fetch URL "https://example.com"
    Then the playground should show fetch content or an error banner

  @stub @keenable @search
  Scenario: Keenable pinned search returns stubbed results or an honest error
    When I pin the playground provider to "Keenable"
    And I submit the playground search query "open data documentation"
    Then the playground should show search results or an error banner

  @stub @keenable @fetch
  Scenario: Keenable pinned fetch returns stubbed content or an honest error
    When I open the playground tab "Fetch"
    And I pin the playground fetch provider to "Keenable"
    And I submit the playground fetch URL "https://example.com"
    Then the playground should show fetch content or an error banner

  @stub @tinyfish @search
  Scenario: Tinyfish pinned search returns stubbed results or an honest error
    When I pin the playground provider to "Tinyfish"
    And I submit the playground search query "open data documentation"
    Then the playground should show search results or an error banner

  @stub @tinyfish @fetch
  Scenario: Tinyfish pinned fetch returns stubbed content or an honest error
    When I open the playground tab "Fetch"
    And I pin the playground fetch provider to "Tinyfish"
    And I submit the playground fetch URL "https://example.com"
    Then the playground should show fetch content or an error banner
