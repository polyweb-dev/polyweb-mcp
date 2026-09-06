Feature: Dashboard application shell
  The dashboard keeps its primary workspaces reachable from the global header.

  Background:
    Given I navigate to the web application

  @smoke
  Scenario: Navigate through every dashboard workspace
    When I select the "Playground" header tab
    Then I should see the "Search Playground" heading
    When I select the "Providers" header tab
    Then I should see the "Providers" heading
    When I select the "Routing" header tab
    Then I should see the "Routing" heading
    When I select the "Usage" header tab
    Then I should see the "Usage" heading
    When I select the "Activity" header tab
    Then I should see the "Activity" heading
    When I select the "Settings" header tab
    Then I should see the "Settings" heading
