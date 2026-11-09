Feature: Dashboard application shell
  The dashboard keeps its primary workspaces reachable from the sidebar.
  C4 URL routing: every workspace is a router link (NavLink) and the URL
  tracks the active view. TabId is unchanged — the "quotas" tab renders at
  the "/system/quotas" path behind the "Quotas" link and System Providers at
  "/system/providers" behind the "Providers" link. Playground, Activity
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
    When I follow the "Quotas" sidebar link
    Then I should see the "Quotas" heading
    And the page URL path should be "/system/quotas"
    When I follow the "Providers" sidebar link
    Then I should see the "Providers" heading
    And the page URL path should be "/system/providers"
