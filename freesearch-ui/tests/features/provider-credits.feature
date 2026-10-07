@stub @ui7
Feature: Provider credit units display honestly
  One credit bar with percent on the right. Credit fraction below the bar with USD value in hover text.
  Unknown fields stay hidden. Fetch controls show only where fetch has support.

  Background:
    Given I navigate to the web application

  @stub @ui7 @finite
  Scenario: U7-B01 Finite card shows one bar with 90 percent and funds
    Given the stubbed provider limits show "Brave finite credits"
    And the stubbed credit totals show "Brave no use"
    When I navigate directly to "/usage"
    Then the Brave credit bar should show "90" percent
    And the Brave card should show "4500 / 5000 CRD"
    And the Brave CRD value should carry "$4.5 left" hover text
    And the Brave card should show one credit bar
    And the usage view should not show "CRD left"
    And the usage view should not show "∞"
    And the Brave card should show the "Sync" action
    And the Brave card should show the "Provider Balance" action
    And the Brave card should show the "Budget Limit" action
    And the Brave card should show the "History" action
    And the Brave card subtitle should contain "Observed from the vendor API"

  @stub @ui7 @precision
  Scenario: U7-B02 Zero tiny and fractional funds stay exact
    Given the stubbed provider limits show "Brave finite credits"
    And the stubbed credit totals show "Brave no use"
    When I navigate directly to "/usage"
    Then the formatted CRD amount "0" should be "0 CRD"
    And the formatted CRD amount "0.04" should be "<0.1 CRD"
    And the formatted CRD amount "0.599" should be "≈0.6 CRD"
    And the formatted CRD amount "4.5" should be "4.5 CRD"

  @stub @ui7 @unknown
  Scenario: U7-B03 Unknown balance price tier and reset show no invented text
    Given the stubbed provider limits show "Brave unknown credits"
    And the stubbed credit totals show "Brave no use"
    When I navigate directly to "/usage"
    Then the usage view should not show "Unknown"
    And the usage view should not show "n/a"
    And the usage view should not show "Not reported"
    And the usage view should not show "Tier split unavailable"
    And the Brave card should show no credit bar

  @stub @ui7 @allowance
  Scenario: U7-B04 Known funds without allowance show amounts but no bar
    Given the stubbed provider limits show "Brave funds without allowance"
    And the stubbed credit totals show "Brave no use"
    When I navigate directly to "/usage"
    Then the Brave card should show "4500" with no total
    And the Brave card should show no credit bar
    And the usage view should not show "CRD left"

  @stub @ui7 @free
  Scenario: U7-B05 Free state shows no invented finite funds
    Given the stubbed provider limits show "Brave free credits"
    And the stubbed credit totals show "Brave no use"
    When I navigate directly to "/usage"
    Then the usage view should show "Free - unmetered"
    And the Brave card should show no credit bar

  @stub @ui7 @debit
  Scenario: U7-B06 One debit refresh moves 4500 to 4495
    Given the stubbed provider limits show "Brave finite credits"
    And the stubbed credit totals show "Brave no use"
    When I navigate directly to "/usage"
    Then the Brave credit bar should show "90" percent
    When the stubbed provider limits show "Brave finite credits after debit"
    And the stubbed credit totals show "Brave one search use"
    And I reload the page
    Then the Brave credit bar should show "89.9" percent
    And the Brave card should show "4495 / 5000 CRD"
    And the Brave CRD value should carry "$4.495 left" hover text

  @stub @ui7 @totals
  Scenario: U7-B07 Repeated fractional debits keep exact USD use
    Given the stubbed provider limits show "Brave finite credits after debit"
    And the stubbed credit totals show "Brave fractional use"
    When I navigate directly to "/usage"
    # Final-polish Item 3c: card shows CRD only with USD in hover text; 0.011 stays a unit oracle in crdCardModel tests.
    Then the Brave CRD value should carry "$4.495 left" hover text

  @stub @ui7 @shared
  Scenario: U7-B08 Shared funds pool two operations with local-only grants
    Given the stubbed provider limits show "Brave finite credits"
    And the stubbed credit totals show "Brave no use"
    When I navigate directly to "/usage"
    And I open the credit details for "Brave"
    Then the credit details should show "Search CRD cost"
    And the credit details should show "Searches left"
    And the credit details should show "Rate limit"
    And the credit details should show "Last sync"
    And the credit details should show "usage page"
    And the credit details should show "Reset"

  @stub @ui7 @fetch
  Scenario: U7-B09 Brave fetch absent shows no fetch row
    Given the stubbed provider limits show "Brave finite credits"
    And the stubbed credit totals show "Brave no use"
    When I navigate directly to "/usage"
    Then the usage view should not show "Fetch credit units left"
    And the usage view should not show "Fetch grant"
    And the price note should have no "fetch" row for "Brave"

  @stub @ui7 @manual
  Scenario: U7-B10 USD manual modal saves 5.00 allowance with 4.12 balance
    Given the stubbed provider limits show "Brave finite credits"
    And the stubbed credit totals show "Brave no use"
    When I navigate directly to "/usage"
    And I open the credit manual entry for "Brave"
    Then the manual entry should show "Credit mode"
    And the manual entry should show "Allowance (USD)"
    And the manual entry should show "Balance remaining (USD)"

  @stub @ui7 @manual-error
  Scenario: U7-B11 Manual cancel invalid error zero and clear stay safe
    Given the stubbed provider limits show "Brave finite credits"
    And the stubbed credit totals show "Brave no use"
    When I navigate directly to "/usage"
    And I open the credit manual entry for "Brave"
    And I cancel the credit dialog
    Then the usage view should show "Brave"

  @stub @ui7 @grant
  Scenario: U7-B12 Grant modal search-only save with version and period
    Given the stubbed provider limits show "Brave finite credits"
    And the stubbed credit totals show "Brave no use"
    When I navigate directly to "/usage"
    And I open the credit grant for "Brave"
    Then the grant form should show "Search credit units (CRD)"
    And the grant form should have no fetch field

  @stub @ui7 @history
  Scenario: U7-B13 History modal pages cursors with correct facts
    Given the stubbed provider limits show "Brave finite credits"
    And the stubbed credit totals show "Brave no use"
    And the stubbed credit history shows "Brave credit history"
    When I navigate directly to "/usage"
    And I open the credit history for "Brave"
    Then the history modal should show "Balance history"
    And the history modal should show "Time"
    And the history modal should show "Old balance"
    And the history modal should show "New balance"

  @stub @ui7 @footer
  Scenario: U7-B14 Footer shows one price note with Brave cost
    Given the stubbed provider limits show "Brave finite credits"
    And the stubbed credit totals show "Brave no use"
    When I navigate directly to "/usage"
    Then the price note should show "1 CRD = USD 0.001 of priced native use"
    And the price note should show "0.005 USD"
    And the price note should show "5 CRD"

  @stub @ui7 @page
  Scenario: U7-B15 Page keeps CRD totals and OAuth slot without native table
    Given the stubbed provider limits show "Brave finite credits"
    And the stubbed credit totals show "Brave one search use"
    When I navigate directly to "/usage"
    Then the usage view should show "Usage totals"
    And the usage view should show "Credit-unit use"
    And the usage view should not show "Provider quota view"

  @stub @ui7 @race
  Scenario: U7-B16 Late older dashboard response cannot restore old funds
    Given the stubbed provider limits show "Brave finite credits"
    And the stubbed credit totals show "Brave no use"
    When I navigate directly to "/usage"
    Then the Brave credit bar should show "90" percent

  @stub @ui7 @keyboard
  Scenario: U7-B17 Grant manual and history modals trap and return focus
    Given the stubbed provider limits show "Brave finite credits"
    And the stubbed credit totals show "Brave no use"
    When I navigate directly to "/usage"
    And I open the credit grant for "Brave"
    Then the grant form should show "Search credit units (CRD)"
    When I cancel the credit dialog
    Then the usage view should show "Brave"

  @stub @ui7 @manual-subtitle
  Scenario: U7-B18 Manual balance card states calculated usage
    Given the stubbed provider limits show "Brave manual balance"
    And the stubbed credit totals show "Brave no use"
    When I navigate directly to "/usage"
    Then the Brave card subtitle should contain "calculated usage"
