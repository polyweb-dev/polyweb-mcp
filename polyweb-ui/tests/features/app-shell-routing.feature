@c4 @stub
Feature: App-shell URL routing (C4)
  Sidebar workspaces are router links (NavLink) over a real BrowserRouter
  history: the URL tracks the view, deep-links render, back/forward/refresh
  restore the view, and pill tabs never change the URL path. TabId is
  unchanged — the "quotas" tab renders at the "/system/quotas" path behind the
  "Quotas" link, and System Providers renders at "/system/providers" behind the
  "Providers" link. The workspace is project first (U1): the root and unknown paths land
  on the last valid project, else on the projects list. Playground and
  Activity are project sections (U2): their former global paths redirect to
  the last project's section, else to the projects list. The stubbed session
  is a system administrator.

  Background:
    Given I navigate to the web application

  @smoke
  Scenario: C4-1 sidebar links change the URL on navigation
    When I follow the "Quotas" sidebar link
    Then I should see the "Quotas" heading
    And the page URL path should be "/system/quotas"

  Scenario: P1-FINAL legacy providers path redirects to System Providers
    When I navigate directly to "/providers"
    Then the page URL path should be "/system/providers"
    And I should see the "Providers" heading

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
      | path              | heading   | link      |
      | /system/quotas    | Quotas    | Quotas    |
      | /system/providers | Providers | Providers |

  Scenario Outline: C4-3 former global <path> without a stored project lands on the projects list
    When I navigate directly to "<path>"
    Then the page URL path should be "/projects"
    And I should see the "Projects" heading

    Examples:
      | path        |
      | /playground |
      | /activity   |
      | /routing    |
      | /system/routing |

  @smoke
  Scenario: C4-4 back and forward restore the view and the current marker
    When I navigate directly to "/system/providers"
    Then I should see the "Providers" heading
    When I follow the "Quotas" sidebar link
    Then the page URL path should be "/system/quotas"
    And I should see the "Quotas" heading
    When I go back in history
    Then the page URL path should be "/system/providers"
    And I should see the "Providers" heading
    And the "Providers" sidebar link should be marked current
    When I go forward in history
    Then the page URL path should be "/system/quotas"
    And I should see the "Quotas" heading
    And the "Quotas" sidebar link should be marked current

  Scenario: C4-4 refresh keeps the deep-linked view
    When I navigate directly to "/system/quotas"
    Then I should see the "Quotas" heading
    When I reload the page
    Then I should see the "Quotas" heading
    And the page URL path should be "/system/quotas"
    And the "Quotas" sidebar link should be marked current

  Scenario: C4-5 quotas tab maps to the system quotas path with router-driven active state
    When I follow the "Quotas" sidebar link
    Then the page URL path should be "/system/quotas"
    And I should see the "Quotas" heading
    And the "Quotas" sidebar link should be marked current
    And the "Quotas" sidebar link should point to "/system/quotas"
    And the sidebar navigation should expose the system administrator links

  Scenario Outline: Retired system key and capacity paths redirect to the vault
    When I navigate directly to "<path>"
    Then the page URL path should be "/account/keys"
    And I should see the "Keys and pools" heading

    Examples:
      | path                |
      | /system/credentials |
      | /system/capacity    |

  Scenario Outline: Retired paths reopen the last selected project
    Given the projects backend is stubbed
    And I am a member of project Alpha with role project_admin
    When I open the workspace page "/projects"
    And I select project Alpha from the project selector
    And I navigate directly to "<path>"
    Then the page URL path should be the "<section>" section of project Alpha

    Examples:
      | path            | section   |
      | /admin/users    | overview  |
      | /routing        | providers |
      | /system/routing | providers |

  Scenario: C4-7 shell keeps the sidebar shell with no legacy header topbar
    Given the stubbed session works in project Alpha
    When I open the "playground" section of project Alpha
    Then I should see the "Playground" heading
    And the shell should expose no header element
    And the sidebar navigation should expose the system administrator links
    When I open the "activity" section of project Alpha
    Then I should see the "Activity" heading
    And the page URL path should be the "activity" section of project Alpha
