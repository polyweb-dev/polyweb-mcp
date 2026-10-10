@sidebar-account-menu @stub
Feature: Sidebar account menu
  The sidebar keeps navigation above the account row. The account row opens
  a popup with the account name, the username, and Sign out. Sign out stays
  in the popup only.

  @sidebar-account-menu @stub
  Scenario: B1 Admin sidebar keeps seven links in order
    Given the sidebar session belongs to an admin account
    When I open the playground workspace for the sidebar check
    Then the sidebar shows seven links in order with exact hrefs
    And the sidebar shows the Account and Admin links

  @sidebar-account-menu @stub
  Scenario Outline: B2 Non-admin sidebar hides the Admin link
    Given the sidebar session belongs to a <role> account
    When I open the playground workspace for the sidebar check
    Then the sidebar shows <count> links without Admin
    And the sidebar shows no Admin link

    Examples:
      | role      | count |
      | developer | 6     |
      | agent     | 3     |

  @sidebar-account-menu @stub
  Scenario: B3 Expanded account row opens the identity popup
    Given the sidebar session belongs to an admin account
    When I open the playground workspace for the sidebar check
    And I activate the expanded account row
    Then the account popup shows the approved identity values and Sign out
    And the sidebar shows no separate Sign out button

  @sidebar-account-menu @stub
  Scenario: B4 Collapsed avatar opens the same popup
    Given the sidebar session belongs to an admin account
    When I open the playground workspace for the sidebar check
    And I collapse the sidebar for the account check
    And I activate the collapsed account avatar
    Then the account popup shows the approved identity values and Sign out
    And the collapsed trigger keeps a complete accessible name

  @sidebar-account-menu @stub
  Scenario: B5 Popup dismissal keeps focus correct
    Given the sidebar session belongs to an admin account
    When I open the playground workspace for the sidebar check
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
    Given the sidebar session belongs to an admin account
    When I open the playground workspace for the sidebar check
    And I open the mobile navigation drawer for the account check
    And I activate the drawer account row
    Then the account popup stays above the drawer
    When I press Escape once for the nested popup
    Then only the account popup closes

  @sidebar-account-menu @stub
  Scenario: B7 Second Escape closes the drawer with focus return
    Given the sidebar session belongs to an admin account
    When I open the playground workspace for the sidebar check
    And I open the mobile navigation drawer for the account check
    And I activate the drawer account row
    And I press Escape once for the nested popup
    And I press Escape again for the drawer
    Then the drawer closes and Open navigation keeps focus

  @sidebar-account-menu @stub
  Scenario: B8 Every permitted link keeps its route
    Given the sidebar session belongs to an admin account
    When I open the playground workspace for the sidebar check
    Then each permitted sidebar link keeps its route and view
    And mobile navigation still closes the drawer on follow

  @sidebar-account-menu @stub
  Scenario: B9 Double Sign out sends one logout operation
    Given the sidebar session belongs to an admin account
    And the sidebar logout stays pending for the double-action check
    When I open the playground workspace for the sidebar check
    And I activate the expanded account row
    And I choose Sign out twice while logout stays pending
    Then the sidebar sends one logout operation
    And the Sign out action stays disabled until completion

  @sidebar-account-menu @stub
  Scenario: B10 Logout success keeps session exit
    Given the sidebar session belongs to an admin account
    And the sidebar logout succeeds for the outcome check
    When I open the playground workspace for the sidebar check
    And I activate the expanded account row
    And I choose Sign out for the outcome check
    Then the sidebar logout outcome is session exit

  @sidebar-account-menu @stub
  Scenario: B10 Logout failure keeps a safe session exit
    Given the sidebar session belongs to an admin account
    And the sidebar logout fails safely for the outcome check
    When I open the playground workspace for the sidebar check
    And I activate the expanded account row
    And I choose Sign out for the outcome check
    Then the failed logout keeps a safe session exit

  @sidebar-account-menu @stub
  Scenario: B11 Long identity and short viewport keep access
    Given the sidebar session belongs to the long-identity account
    When I open the playground workspace for the sidebar check at short height
    Then navigation scrolls and the account row stays accessible
    And the account popup stays within the viewport

  @sidebar-account-menu @stub
  Scenario: B12 Route and mode change resets the popup
    Given the sidebar session belongs to an admin account
    When I open the playground workspace for the sidebar check
    And I activate the expanded account row
    And I follow the Routing link with an open popup
    Then the account popup closes without stale identity
    When I activate the expanded account row
    And I toggle sidebar mode with an open popup
    Then the account popup closes without stale identity

  @sidebar-account-menu @stub
  Scenario Outline: B13 Account page keeps facts without Sign out
    Given the sidebar session belongs to a <role> account
    When I open the account workspace for the sidebar check
    Then the account page keeps facts without Sign out
    And the Admin creation link condition holds for <role>

    Examples:
      | role      |
      | admin     |
      | developer |
      | agent     |

  @sidebar-refinements @sidebar-account-menu @stub
  Scenario: R1 Avatars use larger centered circles
    Given the sidebar session belongs to an admin account
    When I open the playground workspace for the sidebar check
    And I activate the expanded account row
    Then the outside and popup avatars use larger centered circles

  @sidebar-refinements @sidebar-account-menu @stub
  Scenario: R2 Collapsed header reveals the expansion icon on pointer rest
    Given the sidebar session belongs to an admin account
    When I open the playground workspace for the sidebar check
    And I collapse the sidebar for the account check
    Then the idle collapsed header shows the logo
    When I rest the pointer on the expansion control
    Then the expansion icon appears without geometry movement

  @sidebar-refinements @sidebar-account-menu @stub
  Scenario: R3 Keyboard focus reveals and activates the expansion control
    Given the sidebar session belongs to an admin account
    When I open the playground workspace for the sidebar check
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
    Given the sidebar session belongs to an admin account
    When I open the playground workspace for the sidebar check
    And I collapse the sidebar for the account check
    And I activate the logo button without hover
    Then the rail expands with the adjacent collapse control

  @sidebar-refinements @sidebar-account-menu @stub
  Scenario: R5 One inset divider sits above the outside account row
    Given the sidebar session belongs to an admin account
    When I open the playground workspace for the sidebar check
    Then one inset divider sits above the outside row with gaps at both ends
    And no divider separates the outside identity lines
    When I open the mobile navigation drawer for the account check
    Then the drawer account row keeps the same inset divider

  @sidebar-refinements @sidebar-account-menu @stub
  Scenario Outline: R6 Each role shows role outside and email inside
    Given the sidebar session belongs to a <role> account
    When I open the playground workspace for the sidebar check
    Then the outside row shows the username and role without email
    When I activate the expanded account row
    Then the account popup shows the approved identity values and Sign out
    When I collapse the sidebar for the account check
    Then the collapsed trigger keeps a complete accessible name

    Examples:
      | role      |
      | admin     |
      | developer |
      | agent     |

  @sidebar-refinements @sidebar-account-menu @stub
  Scenario: R7 Sidebar contracts stay correct after refinements
    Given the sidebar session belongs to an admin account
    When I open the playground workspace for the sidebar check
    And I collapse the sidebar for the account check
    And I reload the page
    Then the sidebar keeps the stored collapse choice
    When I follow the "Routing" sidebar link
    Then I should see the "Routing" heading
    And the page URL path should be "/routing"
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
