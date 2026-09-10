@stub
Feature: Provider search and fetch against the stubbed backend
  Pinned provider search and fetch go through deterministic /search and
  /fetch stubs. Search asserts results-or-error; fetch asserts
  content-or-error — except Brave fetch, which has no fetch capability and
  must be absent from the fetch picker.

  Background:
    Given I navigate to the web application
    When I navigate directly to "/playground"

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

  # S1 — Ranks fetch table must include Parallel (not just the picker).
  # Brave stays fetch-incapable everywhere (picker + Ranks).
  @stub @parallel @fetch
  Scenario: Parallel appears in the Ranks fetch table
    When I select the "Routing" header tab
    And I open the "Ranks" routing tab
    And I choose the "Fetch" ranks operation
    Then the ranks fetch table should show provider "Parallel"

  @stub @brave @fetch
  Scenario: Brave stays absent from the Ranks fetch table
    When I select the "Routing" header tab
    And I open the "Ranks" routing tab
    And I choose the "Fetch" ranks operation
    Then the ranks fetch table should not show provider "Brave Search"
