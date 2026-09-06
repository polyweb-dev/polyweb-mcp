Feature: Settings workbench
  Settings separates provider routing controls, write-only credentials, and failover policy.

  Background:
    Given I navigate to the web application
    When I select the "Settings" header tab
    Then I should see the "Settings" heading

  @smoke
  Scenario: Settings has only provider, key, and failover tabs
    Then the settings page should expose exactly 3 sub-tabs
    And the settings page should not expose a "Cache" tab
    And the settings page should not expose an "Add provider" button

  Scenario: Provider operation state survives switching settings tabs
    When I open the "Providers" settings tab
    And I turn the "Brave Search" "Search" operation off
    Then the "Brave Search" "Search" operation should be off
    When I open the "Keys" settings tab
    And I open the "Providers" settings tab
    Then the "Brave Search" "Search" operation should remain off

  Scenario: Provider priority arrows stop at registry boundaries
    When I open the "Providers" settings tab
    Then the "Brave Search" upward priority arrow should be disabled
    And the "Parallel" downward priority arrow should be disabled

  @smoke
  Scenario: Save a credential as a masked stored key
    When I open the "Keys" settings tab
    Then the keys tab should show a masked fingerprint containing bullets
    And the keys tab should not contain "Copy", "Burn", "Reveal", or "shown once"
    When I save the key "yc_live_secret_key_6789" for "You.com"
    Then the "You.com" key status should be "Stored"
    And the "You.com" key fingerprint should be "yc_l_••••••••6789"

  Scenario: Failover policy exposes a vertical switch stack with descriptions
    When I open the "Failover" settings tab
    Then the failover switch "Fallback chaining" should be visible
    And the failover switch "Failover on rate limit (429)" should be visible
    And the failover switch "Failover on timeout" should be visible
    And the failover switch "Failover on server error (5xx)" should be visible
    And each failover switch should expose a description
    And the failover operation switches should be vertically stacked
    And the failover row "Cascade depth" should be visible
    And the failover row "Timeout budget" should be visible
