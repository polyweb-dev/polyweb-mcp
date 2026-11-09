@sidebar-account-menu @stub
Feature: Sidebar account menu
  The sidebar keeps navigation above the account row. The account row opens
  a popup with Account and Sign out; the identity moves into the popup when
  the sidebar is collapsed. Sign out stays in the popup only. Accounts carry no role: navigation follows the system
  permissions from GET /api/v1/system/access. A system administrator holds
  every system permission, a settings reader holds only system.settings.read,
  and a member holds no system permission. Playground, Activity and Usage
  are project sections (U2), so the Primary navigation lists the global
  workspaces only. The System group lists "Providers" and "Quotas", then
  "Projects", "Keys and pools", and "Account".

  @sidebar-account-menu @stub
  Scenario: B1 System administrator sidebar keeps its links in order
    Given the sidebar session belongs to a system administrator
    When I open the workspace for the sidebar check
    Then the sidebar shows five links in order with exact hrefs
    And the sidebar shows the Account link
    And the sidebar shows no Accounts link

  @sidebar-account-menu @stub
  Scenario Outline: B2 An account without system.settings.write hides the Accounts link
    Given the sidebar session belongs to the "<account>" account
    When I open the workspace for the sidebar check
    Then the sidebar shows <count> links without an Accounts link
    And the sidebar shows no Accounts link
    And the Primary navigation lists exactly "<links>"

    Examples:
      | account         | count | links                                         |
      | settings reader | 4     | Providers, Quotas, Projects, Account |
      | member          | 2     | Projects, Account                             |

  @sidebar-account-menu @stub
  Scenario Outline: B2b A retired or unauthorized direct URL redirects home
    Given the sidebar session belongs to the "<account>" account
    When I open the gated page "<path>" for the sidebar check
    Then the gated page redirects home to the projects list

    Examples:
      | account              | path                |
      | system administrator | /admin/users        |
      | settings reader      | /admin/users        |
      | member               | /admin/users        |
      | member               | /system/quotas      |
      | member               | /system/providers   |

  @sidebar-account-menu @stub
  Scenario: B3 Expanded account row opens the identity popup
    Given the sidebar session belongs to a system administrator
    When I open the workspace for the sidebar check
    And I activate the expanded account row
    Then the account popup shows the approved identity values and Sign out
    And the sidebar shows no separate Sign out button

  @sidebar-account-menu @stub
  Scenario: B4 Collapsed avatar opens the same popup
    Given the sidebar session belongs to a system administrator
    When I open the workspace for the sidebar check
    And I collapse the sidebar for the account check
    And I activate the collapsed account avatar
    Then the account popup shows the approved identity values and Sign out
    And the collapsed trigger keeps a complete accessible name

  @sidebar-account-menu @stub
  Scenario: B5 Popup dismissal keeps focus correct
    Given the sidebar session belongs to a system administrator
    When I open the workspace for the sidebar check
    And I activate the expanded account row
    And I dismiss the account popup with Escape
    Then the account popup closes and trigger focus returns
    When I activate the expanded account row
    And I dismiss the account popup with an outside click
    Then the account popup closes and destination focus stays
    When I activate the expanded account row
    And I toggle the account popup with the trigger
    Then the account popup closes

  @sidebar-account-menu @stub
  Scenario: B6 Drawer popup stays above with nested Escape order
    Given the sidebar session belongs to a system administrator
    When I open the workspace for the sidebar check
    And I open the mobile navigation drawer for the account check
    And I activate the drawer account row
    Then the account popup stays above the drawer
    When I press Escape once for the nested popup
    Then only the account popup closes

  @sidebar-account-menu @stub
  Scenario: B7 Second Escape closes the drawer with focus return
    Given the sidebar session belongs to a system administrator
    When I open the workspace for the sidebar check
    And I open the mobile navigation drawer for the account check
    And I activate the drawer account row
    And I press Escape once for the nested popup
    And I press Escape again for the drawer
    Then the drawer closes and Open navigation keeps focus

  @sidebar-account-menu @stub
  Scenario: B8 Every permitted link keeps its route
    Given the sidebar session belongs to a system administrator
    When I open the workspace for the sidebar check
    Then each permitted sidebar link keeps its route and view
    And mobile navigation still closes the drawer on follow

  @sidebar-account-menu @stub
  Scenario: B8b Every Project link of a project member keeps its route
    Given the sidebar session belongs to a system administrator
    And the stubbed session works in project Alpha
    When I open the "overview" section of project Alpha
    Then each Project link of a project member keeps its route and view

  @sidebar-account-menu @stub
  Scenario: B9 Double Sign out sends one logout operation
    Given the sidebar session belongs to a system administrator
    And the sidebar logout stays pending for the double-action check
    When I open the workspace for the sidebar check
    And I activate the expanded account row
    And I choose Sign out twice while logout stays pending
    Then the sidebar sends one logout operation
    And the Sign out action stays disabled until completion

  @sidebar-account-menu @stub
  Scenario: B10 Logout success keeps session exit
    Given the sidebar session belongs to a system administrator
    And the sidebar logout succeeds for the outcome check
    When I open the workspace for the sidebar check
    And I activate the expanded account row
    And I choose Sign out for the outcome check
    Then the sidebar logout outcome is session exit

  @sidebar-account-menu @stub
  Scenario: B10 Logout failure keeps a safe session exit
    Given the sidebar session belongs to a system administrator
    And the sidebar logout fails safely for the outcome check
    When I open the workspace for the sidebar check
    And I activate the expanded account row
    And I choose Sign out for the outcome check
    Then the failed logout keeps a safe session exit

  @sidebar-account-menu @stub
  Scenario: B11 Long identity and short viewport keep access
    Given the sidebar session belongs to the long-identity account
    When I open the workspace for the sidebar check at short height
    Then navigation scrolls and the account row stays accessible
    And the account popup stays within the viewport

  @sidebar-account-menu @stub
  Scenario: B12 Route and mode change resets the popup
    Given the sidebar session belongs to a system administrator
    When I open the workspace for the sidebar check
    And I activate the expanded account row
    And I follow the Quotas link with an open popup
    Then the account popup closes without stale identity
    When I activate the expanded account row
    And I toggle sidebar mode with an open popup
    Then the account popup closes without stale identity

  @sidebar-account-menu @stub
  Scenario Outline: B13 Account page keeps facts without Sign out
    Given the sidebar session belongs to the "<account>" account
    When I open the account workspace for the sidebar check
    Then the account page keeps facts without Sign out
    And the account page shows no role
    And the account page has no account creation link

    Examples:
      | account              |
      | system administrator |
      | settings reader      |
      | member               |

  @sidebar-refinements @sidebar-account-menu @stub
  Scenario: R1 Avatars use larger centered circles
    Given the sidebar session belongs to a system administrator
    When I open the workspace for the sidebar check
    And I collapse the sidebar for the account check
    And I activate the collapsed account avatar
    Then the outside and popup avatars use larger centered circles

  @sidebar-refinements @sidebar-account-menu @stub
  Scenario: R2 Collapsed header reveals the expansion icon on pointer rest
    Given the sidebar session belongs to a system administrator
    When I open the workspace for the sidebar check
    And I collapse the sidebar for the account check
    Then the idle collapsed header shows the logo
    When I rest the pointer on the expansion control
    Then the expansion icon appears without geometry movement

  @sidebar-refinements @sidebar-account-menu @stub
  Scenario: R3 Keyboard focus reveals and activates the expansion control
    Given the sidebar session belongs to a system administrator
    When I open the workspace for the sidebar check
    And I collapse the sidebar for the account check
    And I focus the expansion control with the keyboard
    Then keyboard focus reveals the expansion control
    When I press Enter on the focused expansion control
    Then the rail expands with the adjacent collapse control
    When I collapse the sidebar for the account check
    And I focus the expansion control with the keyboard
    And I press Space on the focused expansion control
    Then the rail expands with the adjacent collapse control

  @sidebar-refinements @sidebar-account-menu @stub
  Scenario: R4 Logo button activates without hover
    Given the sidebar session belongs to a system administrator
    When I open the workspace for the sidebar check
    And I collapse the sidebar for the account check
    And I activate the logo button without hover
    Then the rail expands with the adjacent collapse control

  @sidebar-refinements @sidebar-account-menu @stub
  Scenario: R5 One inset divider sits above the outside account row
    Given the sidebar session belongs to a system administrator
    When I open the workspace for the sidebar check
    Then one inset divider sits above the outside row with gaps at both ends
    And no divider separates the outside identity lines
    When I open the mobile navigation drawer for the account check
    Then the drawer account row keeps the same inset divider

  @sidebar-refinements @sidebar-account-menu @stub
  Scenario Outline: R6 Each account shows its name and email without a role
    Given the sidebar session belongs to the "<account>" account
    When I open the workspace for the sidebar check
    Then the outside row shows the display name and email without a role
    When I activate the expanded account row
    Then the account popup shows the approved identity values and Sign out
    When I collapse the sidebar for the account check
    Then the collapsed trigger keeps a complete accessible name

    Examples:
      | account              |
      | system administrator |
      | settings reader      |
      | member               |

  @sidebar-refinements @sidebar-account-menu @stub
  Scenario: R7 Sidebar contracts stay correct after refinements
    Given the sidebar session belongs to a system administrator
    When I open the workspace for the sidebar check
    And I collapse the sidebar for the account check
    And I reload the page
    Then the sidebar keeps the stored collapse choice
    When I follow the "Quotas" sidebar link
    Then I should see the "Quotas" heading
    And the page URL path should be "/system/quotas"
    When I open the mobile navigation drawer for the account check
    And I activate the drawer account row
    And I press Escape once for the nested popup
    And I press Escape again for the drawer
    Then the drawer closes and Open navigation keeps focus

  @sidebar-refinements @sidebar-account-menu @stub
  Scenario: R8 Compact viewport keeps access without overflow
    Given the sidebar session belongs to the long-identity account
    When I open the compact workspace at 320 pixels
    Then the document has no horizontal overflow at 320 pixels
    When I open the navigation drawer without viewport change
    And I activate the drawer account row
    Then the account popup stays above the drawer
