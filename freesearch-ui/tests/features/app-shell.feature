Feature: Dashboard application shell
  The dashboard keeps its primary workspaces reachable from the sidebar.
  C4 URL routing: every workspace is a router link (NavLink) and the URL
  tracks the active view. TabId is unchanged — the "quotas" tab renders at
  the "/usage" path behind the "Provider usage" link. Playground, Activity
  and Usage are project sections (U2) behind the Project navigation.

  Background:
    Given I navigate to the web application

  @smoke @stub
  Scenario: Navigate through every dashboard workspace via sidebar links
    Given the stubbed session works in project Alpha
    When I open the "overview" section of project Alpha
    And I follow the "Playground" link of the Project navigation
    Then I should see the "Playground" heading
    And the page URL path should be the "playground" section of project Alpha
    When I follow the "Activity" link of the Project navigation
    Then I should see the "Activity" heading
    And the page URL path should be the "activity" section of project Alpha
    When I follow the "Usage" link of the Project navigation
    Then I should see the "Usage" heading
    And the page URL path should be the "usage" section of project Alpha
    When I follow the "Routing" sidebar link
    Then I should see the "Routing" heading
    And the page URL path should be "/routing"
    When I follow the "Provider usage" sidebar link
    Then I should see the "Usage" heading
    And the page URL path should be "/usage"
    When I follow the "Provider settings" sidebar link
    Then I should see the "Settings" heading
    And the page URL path should be "/settings"
