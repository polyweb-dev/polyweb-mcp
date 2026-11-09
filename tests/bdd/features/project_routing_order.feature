@routing
Feature: Project provider order
  Scenario: An admin chooses free providers first for search
    Given an offline project with free and paid search providers
    When the project admin chooses Free first for Search
    Then the Search order lists the free provider first
    When the project admin submits a search
    Then the search uses the free provider
