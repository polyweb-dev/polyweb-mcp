Feature: Dashboard application shell
  The dashboard keeps its primary workspaces reachable from the sidebar.
  C4 URL routing: every workspace is a router link (NavLink) and the URL
  tracks the active view. TabId is unchanged — the "quotas" tab renders at
  the "/usage" path.

  Background:
    Given I navigate to the web application

  @smoke @stub
  Scenario: Navigate through every dashboard workspace via sidebar links
    When I follow the "Playground" sidebar link
    Then I should see the "Search Playground" heading
    And the page URL path should be "/playground"
    When I follow the "Routing" sidebar link
    Then I should see the "Routing" heading
    And the page URL path should be "/routing"
    When I follow the "Usage" sidebar link
    Then I should see the "Usage" heading
    And the page URL path should be "/usage"
    When I follow the "Activity" sidebar link
    Then I should see the "Activity" heading
    And the page URL path should be "/activity"
    When I follow the "Settings" sidebar link
    Then I should see the "Settings" heading
    And the page URL path should be "/settings"
