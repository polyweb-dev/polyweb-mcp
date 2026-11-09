@stub @keys-pools
Feature: Account keys and pools
  Scenario: An owner supplies a project from a vault key
    Given the projects backend is stubbed for a system administrator
    And the provider configuration is stubbed
    And I am a member of project Alpha with role project_admin
    When I open Keys and pools
    And I add a Brave Search vault key labelled "Alpha Brave" with a fake secret
    Then the fake vault secret is sent once and is not exposed in the browser
    When I create a Search pool "Alpha Search" for project Alpha on key "Alpha Brave"
    And I open the Providers page of project Alpha
    Then the Search provider order shows "Alpha Search" for "Brave Search"
