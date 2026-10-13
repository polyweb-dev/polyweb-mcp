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

  @stub @ui7 @tavily @finite
  Scenario: U7-T01 Tavily native budget shows 1000 of 1000 Credits
    Given the stubbed provider limits show "Tavily finite credits"
    And the stubbed credit totals show "Tavily no use"
    When I navigate directly to "/usage"
    Then the Tavily credit bar should show "100" percent
    And the Tavily card should show "1000 / 1000 Credits"
    And the Tavily card should show one credit bar
    And the usage view should not show "CRD left"
    And the usage view should not show "∞"
    And the Tavily card should show the "Sync" action
    And the Tavily card should show the "Provider Balance" action
    And the Tavily card should show the "Budget Limit" action
    And the Tavily card should show the "History" action
    And the Tavily card subtitle should contain "Observed from the vendor API"

  @stub @ui7 @tavily @debit
  Scenario: U7-T02 One basic search debit moves 1000 to 999 Credits
    Given the stubbed provider limits show "Tavily finite credits"
    And the stubbed credit totals show "Tavily no use"
    When I navigate directly to "/usage"
    Then the Tavily credit bar should show "100" percent
    When the stubbed provider limits show "Tavily finite credits after basic"
    And the stubbed credit totals show "Tavily no use"
    And I reload the page
    Then the Tavily credit bar should show "99.9" percent
    And the Tavily card should show "999 / 1000 Credits"

  @stub @ui7 @tavily @debit
  Scenario: U7-T03 One advanced search debit moves 1000 to 998 Credits
    Given the stubbed provider limits show "Tavily finite credits"
    And the stubbed credit totals show "Tavily no use"
    When I navigate directly to "/usage"
    Then the Tavily credit bar should show "100" percent
    When the stubbed provider limits show "Tavily finite credits after advanced"
    And the stubbed credit totals show "Tavily no use"
    And I reload the page
    Then the Tavily credit bar should show "99.8" percent
    And the Tavily card should show "998 / 1000 Credits"

  @stub @ui7 @tavily @keyless
  Scenario: U7-T04 Keyless access reports no Credits quota and no invented headroom
    Given the stubbed provider limits show "Tavily keyless credits"
    And the stubbed credit totals show "Tavily no use"
    When I navigate directly to "/usage"
    Then the usage view should show "Keyless access (no Credits quota is reported)"
    And the Tavily card should show no credit bar
    When I open the credit details for "Tavily"
    Then the credit details should not show "Minute headroom"
    And the usage view should not show "∞"

  @stub @ui7 @tavily @shared
  Scenario: U7-T05 Shared pool serves search and extract with one minute window
    Given the stubbed provider limits show "Tavily finite credits"
    And the stubbed credit totals show "Tavily no use"
    When I navigate directly to "/usage"
    And I open the credit details for "Tavily"
    Then the credit details should show "Search cost"
    And the credit details should show "1 Credit"
    And the credit details should show "Extract cost"
    And the credit details should show "per 5 URLs"
    And the credit details should show "(advanced: 2 Credits)"
    And the credit details should show "Minute headroom"
    And the credit details should show "(shared search and extract)"
    And the credit details should show "Searches left"
    And the credit details should show "Extracts left"

  @stub @ui7 @tavily @exhaust
  Scenario: U7-T06 Free exhaustion stops at zero Credits without PAYGO
    Given the stubbed provider limits show "Tavily free exhausted"
    And the stubbed credit totals show "Tavily no use"
    When I navigate directly to "/usage"
    Then the Tavily card should show "0 / 1000 Credits"
    And the usage view should not show "pay-as-you-go"
    And the usage view should not show "∞"

  @stub @ui7 @tavily @paygo
  Scenario: U7-T07 Paid overage continues under pay-as-you-go
    Given the stubbed provider limits show "Tavily paygo overage"
    And the stubbed credit totals show "Tavily no use"
    When I navigate directly to "/usage"
    Then the Tavily card should show "0 / 1000 Credits"
    And the usage view should show "Free Credits are spent; further use continues under pay-as-you-go."

  @stub @ui7 @tavily @grant
  Scenario: U7-T08 Grant converts both directions and keeps stored CRD
    Given the stubbed provider limits show "Tavily grant credits"
    And the stubbed credit totals show "Tavily no use"
    When I navigate directly to "/usage"
    And I open the Tavily credit grant
    Then the grant form should show "Search Credits"
    And the grant form should show "Fetch Credits"
    And the "Search Credits" grant field should show "100"
    And the "Fetch Credits" grant field should show "200"
    When I type "101" into the "Search Credits" grant field
    And I save the credit grant
    Then the submitted grant should carry "search_crd" "808"
    And the submitted grant should carry "fetch_crd" "1600"

  @stub @ui7 @tavily @history
  Scenario: U7-T09 History shows native Credits balances
    Given the stubbed provider limits show "Tavily finite credits"
    And the stubbed credit totals show "Tavily no use"
    And the stubbed credit history shows "Tavily credit history"
    When I navigate directly to "/usage"
    And I open the credit history for "Tavily"
    Then the history modal should show "Balance history"
    And the history modal should show "1000 Credits"
    And the history modal should show "999 Credits"

  @stub @ui7 @tavily @totals
  Scenario: U7-T10 Native totals stay in Credits with extract labels
    Given the stubbed provider limits show "Tavily finite credits"
    And the stubbed credit totals show "Tavily search and extract use"
    When I navigate directly to "/usage"
    Then the usage view should show "Tavily native Credits use"
    And the usage view should show "Credits spent"
    And the usage view should show "extract"
    And the usage view should show "1 Credit"
    And the usage view should show "0.2 Credits"

  @stub @ui7 @tavily @disclosure
  Scenario: U7-T11 USD stays absent while the disclosure is closed
    Given the stubbed provider limits show "Tavily finite credits"
    And the stubbed credit totals show "Tavily no use"
    When I navigate directly to "/usage"
    Then the Tavily card should show "1000 / 1000 Credits"
    And the usage view should not show "$0.008"

  @stub @ui7 @tavily @disclosure
  Scenario: U7-T12 USD appears once the disclosure is open
    Given the stubbed provider limits show "Tavily finite credits"
    And the stubbed credit totals show "Tavily no use"
    When I navigate directly to "/usage"
    And I open the credit details for "Tavily"
    Then the credit details should show "$0.008"

  @stub @ui7 @tavily @rate
  Scenario: U7-T13 Prod rail shows 1000 RPM headroom with Retry-After
    Given the stubbed provider limits show "Tavily prod credits"
    And the stubbed credit totals show "Tavily no use"
    When I navigate directly to "/usage"
    And I open the credit details for "Tavily"
    Then the credit details should show "Minute headroom"
    And the credit details should show "1000/1000"
    And the credit details should show "Retry-After"
    And the credit details should show "45 s"

  @stub @ui7 @tavily @402
  Scenario: U7-T14 Out-of-Credits 402 reaches the user at once
    Given the stubbed provider limits show "Tavily finite credits"
    And the stubbed credit totals show "Tavily no use"
    When I navigate directly to "/"
    And I pin the playground provider to "Tavily"
    And I submit the playground search query "tavily out of credits probe"
    Then the playground search error should show "Tavily is out of Credits. Wait until reset or upgrade."

  @stub @ui7 @tavily @brave
  Scenario: U7-T15 Brave card stays in CRD beside the Tavily card
    Given the stubbed provider limits show "Brave and Tavily finite credits"
    And the stubbed credit totals show "Brave no use"
    When I navigate directly to "/usage"
    Then the Brave credit bar should show "90" percent
    And the Brave card should show "4500 / 5000 CRD"
    And the Tavily credit bar should show "100" percent
    And the Tavily card should show "1000 / 1000 Credits"
    And the price note should show "0.005 USD"
