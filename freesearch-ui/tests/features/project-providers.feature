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
