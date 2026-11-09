@mobile
Feature: Visual and keyboard regression
  Visual and keyboard contracts remain deterministic across desktop and mobile layouts.

  @visual
  Scenario: V3 mobile settings shell
    Given the sidebar session belongs to a system administrator
    And I open the visual app at 390 by 844
    When I select the "Providers" header tab
    Then the visual page screenshot "settings-mobile.png" should match

  @keyboard @visual
  Scenario: K2 keyboard toggles fallback and reaches max attempts
    Given the sidebar session belongs to a system administrator
    And I open the visual app at 390 by 844
    When I move to the "Providers" view using keyboard only
    And I focus the "Fallback" switch using keyboard only
    And I press Space on the focused fallback switch
    Then the max attempts controls should remain reachable by Tab
    And the visual page screenshot "failover-keyboard-toggle.png" should match
