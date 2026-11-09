@project-providers @stub
Feature: Project providers
  Scenario: Free-first Search order places a keyless provider first
    Given the projects backend is stubbed for a system administrator
    And the provider configuration is stubbed
    And I am a member of project Alpha with role project_admin
    And Search has a keyed provider and keyless Keenable
    When I open the Providers page of project Alpha
    And I order Search providers by Free first
    Then keyless Keenable is first in the Search order

  Scenario: Search order and pool operations stay independent from Fetch
    Given the projects backend is stubbed for a system administrator
    And the provider configuration is stubbed
    And I am a member of project Alpha with role project_admin
    And Alpha has a Tavily pool for Search and Fetch
    When I open the Providers page of project Alpha
    And I move Keenable to the top of the Search order
    Then the Fetch order remains unchanged
    When I confirm stopping Tavily Search
    And I reload the Providers page
    Then Tavily serves Fetch but not Search
