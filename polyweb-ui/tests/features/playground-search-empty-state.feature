@pg-s1 @stub
Feature: Playground search empty state (PG-S1)
  The full-width composer stays docked at the top from the first render.
  Results appear below it and submissions preserve the form value.

  Background:
    Given the stubbed session works in project Alpha

  Scenario: PG-S1-1 idle search starts docked at full width
    When I open the "playground" section of project Alpha
    Then the search request zone should be in docked state
    And the search form should be present with no search results

  Scenario: PG-S1-2 submitting a search keeps the form docked with results below
    When I open the "playground" section of project Alpha
    And I submit the playground search query "hannover weather today"
    Then the search request zone should be in docked state
    And the playground should show search results or an error banner
    And the search results should render below the search form

  Scenario: PG-S1-3 first search failure pins the docked top state
    When I open the "playground" section of project Alpha
    And I submit the playground search query "doomed query"
    Then the search request zone should be in docked state
    And the search form should be present with no search results

  Scenario: PG-S1-4 the fixed composer keeps its form value after submission
    When I open the "playground" section of project Alpha
    Then the search request zone should stay full width without a layout transition
    When I submit the playground search query "focus retention query"
    Then the search form should keep its value "focus retention query"
    And the search request zone should be in docked state
