@control @vault
Feature: Search through a project provider pool
  A provider owner can share capacity with project developers without sharing the key.

  Scenario: A developer searches through the provider owner's vault pool
    Given an offline project with a provider owner and a developer
    When the provider owner adds a Brave vault key and creates a search pool for the project
    And the developer searches the project with search permission
    Then the search is served by Brave using the pooled vault key
