@stub @quota
Feature: Provider quota display stays honest
  The usage view renders one credit bar per card with the exact CRD fraction.
  Unknown fields stay hidden and invented balances never appear.
  Manual entry and OAuth pairing keep their action-only controls.

  Background:
    Given I navigate to the web application

  @stub @quota @brave
  Scenario: Brave finite credits render one bar with exact funds
    Given the stubbed provider limits show "Brave finite credits"
    And the stubbed credit totals show "Brave no use"
    When I navigate directly to "/usage"
    Then I should see the "Usage" heading
    And the Brave credit bar should show "90" percent
    And the Brave card should show "4500 / 5000 CRD"
    And the Brave CRD value should carry "$4.5 left" hover text
    And the Brave card subtitle should contain "Observed from the vendor API"
    And the usage view should not show "CRD left"
    And the usage view should not show "∞"
    And the usage view should not show "n/a"

  @stub @quota @parallel
  Scenario: Parallel without a card keeps an action slot and no invented balance
    Given the stubbed provider limits show "Brave finite credits"
    And the stubbed credit totals show "Brave no use"
    When I navigate directly to "/usage"
    Then I should see the "Usage" heading
    And the usage view should show "How credit units are priced"
    And the usage view should not show "∞"
    And the usage view should not show "Tier split unavailable"

  @stub @quota @manual
  Scenario: Brave manual entry opens a USD balance dialog from the card
    Given the stubbed provider limits show "Brave finite credits"
    And the stubbed credit totals show "Brave no use"
    When I navigate directly to "/usage"
    And I open the credit manual entry for "brave"
    Then the manual entry should show "Credit mode"
    And the manual entry should show "Allowance (USD)"
    And the manual entry should show "Balance remaining (USD)"
    When I cancel the credit dialog
    Then the usage view should show "Brave"

  @stub @quota @oauth
  Scenario: Parallel OAuth pairing keeps its connect controls
    Given the stubbed provider limits show "Brave finite credits"
    And the stubbed credit totals show "Brave no use"
    And the stubbed OAuth pairing for "parallel" is empty
    When I navigate directly to "/usage"
    And I open the OAuth pairing for provider "parallel"
    Then the pairing code "ABCD-EFGH" should be visible
    When the stubbed OAuth status for "parallel" becomes "ready"
    Then the OAuth disconnect control should be visible
    And the usage view should not show "∞"

  @stub @quota @keenable
  Scenario: Unknown credits render no invented bar or funds
    Given the stubbed provider limits show "Brave unknown credits"
    And the stubbed credit totals show "Brave no use"
    When I navigate directly to "/usage"
    Then I should see the "Usage" heading
    And the Brave card should show no credit bar
    And the usage view should not show "Unknown"
    And the usage view should not show "n/a"
    And the usage view should not show "∞"
