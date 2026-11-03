Feature: Visual and keyboard regression
  Visual and keyboard contracts remain deterministic across desktop and mobile layouts.

  @visual
  Scenario: V1 desktop routing shell
    Given the sidebar session belongs to a system administrator
    And I open the visual app at 1440 by 900
    When I select the "Routing" header tab
    Then I should see the "Routing" heading
    And the visual page screenshot "routing-desktop.png" should match

  @visual
  Scenario: V2 mobile simulator shell
    Given the sidebar session belongs to a system administrator
    And I open the visual app at 390 by 844
    When I select the "Routing" header tab
    And I open the "Simulator" routing tab
    Then the visual page screenshot "simulator-mobile.png" should match

  @visual
  Scenario: V3 mobile settings shell
    Given the sidebar session belongs to a system administrator
    And I open the visual app at 390 by 844
    When I select the "Provider settings" header tab
    And I open the "Providers" settings tab
    Then the visual page screenshot "settings-mobile.png" should match

  @visual
  Scenario: R1 reduced motion removes transition timing
    Given the sidebar session belongs to a system administrator
    And I open the visual app at 1440 by 900 with reduced motion
    When I select the "Routing" header tab
    Then I should see the "Routing" heading
    And reduced-motion transitions should be disabled
    And the visual page screenshot "routing-reduced-motion.png" should match

  @keyboard @visual
  Scenario: K1 keyboard focus follows the header and routing controls
    Given the sidebar session belongs to a system administrator
    And I open the visual app at 1440 by 900
    When I walk from the header through Routing with keyboard only
    Then the focused-control screenshot "routing-keyboard-focus.png" should match

  @keyboard @visual
  Scenario: K2 keyboard toggles failover without trapping sub-switches
    Given the sidebar session belongs to a system administrator
    And I open the visual app at 390 by 844
    When I move to the "Provider settings" view using keyboard only
    And I open the "Failover" settings tab using keyboard only
    And I focus the "Fallback chaining" switch using keyboard only
    And I press Space on the focused failover switch
    Then the failover sub-switches should remain reachable by Tab
    And the visual page screenshot "failover-keyboard-toggle.png" should match

  @keyboard @visual
  Scenario: K3 keyboard changes the simulator operation
    Given the sidebar session belongs to a system administrator
    And I open the visual app at 390 by 844
    When I move to the "Routing" view using keyboard only
    And I open the "Simulator" routing tab using keyboard only
    And I choose "Fetch" in the simulator operation using keyboard only
    Then the simulator input placeholder should be "Type simulated URL..."
    And the visual page screenshot "simulator-fetch-keyboard.png" should match
