@stub @quota
Feature: Provider quota display stays honest
  The usage view renders verbatim quota strings with em-dash blanks (never
  an infinity marker). Brave shows observed requests; Parallel seeded shows
  a USD budget while unseeded shows an explainer instead of a balance;
  Keenable keyless shows rolling hourly request headroom with a shared-pool
  caveat rather than presenting it as a monthly allowance.

  Background:
    Given I navigate to the web application

  @stub @quota @brave
  Scenario: Brave observed quota renders verbatim with confidence
    Given the stubbed dashboard shows "Brave observed quota"
    When I navigate directly to "/usage"
    Then I should see the "Usage" heading
    And the usage view should show "950"
    And the usage view should show "1000"
    And the usage view should show "requests"
    And the usage view should show "observed"
    And the usage view should show "—"
    And the usage view should not show "∞"

  @stub @quota @parallel
  Scenario: Parallel seeded spend and unseeded explainer stay honest
    Given the stubbed dashboard shows "Parallel seeded quota"
    When I navigate directly to "/usage"
    Then I should see the "Usage" heading
    And the usage view should show "3.75/5.00"
    And the usage view should show "USD"
    And the usage view should show "estimated"
    Given the stubbed dashboard shows "Parallel unseeded quota"
    And I reload the page
    Then the usage view should show "Budget not configured"
    And the usage view should show "Monthly"
    And the usage view should show "No API-key balance endpoint is available. Configure a local monthly USD budget to calculate remaining capacity."
    And the usage view should show "—"
    And the usage view should not show "∞"

  @stub @quota @manual
  Scenario: Brave manual budget entry shows an estimated overlay
    Given the stubbed dashboard shows "Brave observed quota"
    And the stubbed manual quota for "brave" is empty
    When I navigate directly to "/usage"
    And I open the manual budget entry for provider "brave"
    And I enter the manual billing window "2026-09-01" to "2026-09-30" with allowance "5.00" and usage "0.88"
    And I save the manual budget entry
    Then the usage view should show "82.4% remaining"
    And the usage view should show "Manual Entry"
    And the manual overlay progress bar for provider "brave" should show "82.4"
    And the usage view should show "Vendor: 950/1000 requests"
    And the usage view should show "observed"
    And the usage view should show "estimated"
    And the usage view should not show "95% remaining"
    And the usage view should not show "∞"

  @stub @quota @oauth
  Scenario: Parallel OAuth pairing shows an authoritative balance
    Given the stubbed dashboard shows "Parallel unseeded quota"
    And the stubbed OAuth pairing for "parallel" is empty
    When I navigate directly to "/usage"
    And I open the OAuth pairing for provider "parallel"
    Then the pairing code "ABCD-EFGH" should be visible
    When the stubbed OAuth status for "parallel" becomes "ready"
    And the stubbed dashboard shows "Parallel paired quota"
    Then the pairing should close
    And the usage view should show "Balance available"
    And the usage view should show "3.75"
    And the OAuth disconnect control should be visible
    And the usage view should not show "Budget not configured"
    And the usage view should not show "∞"

  @stub @quota @keenable
  Scenario: Keenable keyless pool renders rolling hourly headroom
    Given the stubbed dashboard shows "Keenable keyless quota"
    When I navigate directly to "/usage"
    Then I should see the "Usage" heading
    And the usage view should show "99.9% remaining"
    And the usage view should show "999/1000 requests"
    And the usage view should show "observed"
    And the usage view should show "hourly"
    And the usage view should show "locally observed"
    And the usage view should show "shared rate limits still apply"
    And the usage view should not show "∞"
