@pg-s1 @stub
Feature: Playground search empty state (PG-S1)
  Before search the page is empty and looks weird; like Google it should be
  centered when empty, move to the top when used with results below, with a
  smooth animation. The request form is the same element — only its wrapper
  toggles centered-hero vs top-docked.

  Background:
    Given I navigate to the web application

  Scenario: PG-S1-1 idle search is centered like Google
    When I navigate directly to "/playground"
    Then the search request zone should be in hero state
    And the search form should be present with no search results

  Scenario: PG-S1-2 submitting a search docks the form with results below
    When I navigate directly to "/playground"
    And I submit the playground search query "hannover weather today"
    Then the search request zone should be in docked state
    And the playground should show search results or an error banner
    And the search results should render below the search form

  Scenario: PG-S1-3 first search failure pins the docked top state
    When I navigate directly to "/playground"
    And I submit the playground search query "doomed query"
    Then the search request zone should be in docked state
    And the search form should be present with no search results

  Scenario: PG-S1-4 hero-to-docked transition is smooth and keeps the same form
    When I navigate directly to "/playground"
    Then the search request zone should animate smoothly
    When I submit the playground search query "focus retention query"
    Then the search form should keep its value "focus retention query"
    And the search request zone should be in docked state
