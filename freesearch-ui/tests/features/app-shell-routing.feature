@c4 @stub
Feature: App-shell URL routing (C4)
  Sidebar workspaces are router links (NavLink) over a real BrowserRouter
  history: the URL tracks the view, deep-links render, back/forward/refresh
  restore the view, and pill tabs never touch the URL. TabId is unchanged —
  the "quotas" tab renders at the "/usage" path. The workspace is project
  first (U1): the root and unknown paths land on the last valid project, else
  on the projects list. The stubbed session is a system administrator.

  Background:
    Given I navigate to the web application

  @smoke
  Scenario: C4-1 sidebar links change the URL on navigation
    When I follow the "Routing" sidebar link
    Then I should see the "Routing" heading
    And the page URL path should be "/routing"
    When I follow the "Usage" sidebar link
    Then I should see the "Usage" heading
    And the page URL path should be "/usage"

  Scenario: P1-FINAL legacy providers path redirects to settings
    When I navigate directly to "/providers"
    Then the page URL path should be "/settings"
    And I should see the "Settings" heading

  Scenario: C4-2 root path without a stored project redirects to the projects list
    When I navigate directly to "/"
    Then the page URL path should be "/projects"
    And I should see the "Projects" heading

  Scenario: C4-2 unknown path without a stored project falls back to the projects list
    When I navigate directly to "/no-such-view"
    Then the page URL path should be "/projects"
    And I should see the "Projects" heading

  Scenario Outline: C4-3 deep links render their view with the current marker
    When I navigate directly to "<path>"
    Then I should see the "<heading>" heading
    And the page URL path should be "<path>"
    And the "<link>" sidebar link should be marked current

    Examples:
      | path        | heading           | link       |
      | /playground | Search Playground | Playground |
      | /routing    | Routing           | Routing    |
      | /usage      | Usage             | Usage      |
      | /activity   | Activity          | Activity   |
      | /settings   | Settings          | Settings   |

  @smoke
  Scenario: C4-4 back and forward restore the view and the current marker
    When I navigate directly to "/settings"
    Then I should see the "Settings" heading
    When I follow the "Routing" sidebar link
    Then the page URL path should be "/routing"
    And I should see the "Routing" heading
    When I go back in history
    Then the page URL path should be "/settings"
    And I should see the "Settings" heading
    And the "Settings" sidebar link should be marked current
    When I go forward in history
    Then the page URL path should be "/routing"
    And I should see the "Routing" heading
    And the "Routing" sidebar link should be marked current

  Scenario: C4-4 refresh keeps the deep-linked view
    When I navigate directly to "/routing"
    Then I should see the "Routing" heading
    When I reload the page
    Then I should see the "Routing" heading
    And the page URL path should be "/routing"
    And the "Routing" sidebar link should be marked current

  Scenario: C4-5 quotas tab maps to the usage path with router-driven active state
    When I follow the "Usage" sidebar link
    Then the page URL path should be "/usage"
    And I should see the "Usage" heading
    And the "Usage" sidebar link should be marked current
    And the "Usage" sidebar link should point to "/usage"
    And the sidebar navigation should expose the system administrator links

  Scenario: C4-6 routing pill tabs leave the URL unchanged
    When I navigate directly to "/routing"
    Then I should see the "Routing" heading
    When I open the "Simulator" routing tab
    Then the page URL path should still be "/routing"
    When I open the "Ranks" routing tab
    Then the page URL path should still be "/routing"
    When I open the "Resilience" routing tab
    Then the page URL path should still be "/routing"

  Scenario: C4-6 settings pill tabs leave the URL unchanged
    When I navigate directly to "/settings"
    Then I should see the "Settings" heading
    When I open the "Keys" settings tab
    Then the page URL path should still be "/settings"
    When I open the "Failover" settings tab
    Then the page URL path should still be "/settings"

  Scenario: C4-7 shell keeps the sidebar shell with no legacy header topbar
    When I navigate directly to "/playground"
    Then I should see the "Search Playground" heading
    And the shell should expose no header element
    And the sidebar navigation should expose the system administrator links
    When I navigate directly to "/activity"
    Then I should see the "Activity" heading
    And the page URL path should be "/activity"
