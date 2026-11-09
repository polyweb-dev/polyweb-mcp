@stub @quota
Feature: Provider quota display stays honest
  The usage view renders one credit bar per card with the exact USD fraction.
  Unknown fields stay hidden and invented balances never appear.
  Manual entry keeps its action-only controls. Parallel OAuth is managed in
  Keys and pools, which the Quotas page links to.

  Background:
    Given I navigate to the web application

  @stub @quota @brave
  Scenario: Brave finite credits render one bar with exact funds
    Given the stubbed provider limits show "Brave finite credits"
    And the stubbed credit totals show "Brave no use"
    And the Brave key "Brave work" reports "1234.5" USD remaining
    When I navigate directly to "/system/quotas"
    Then I should see the "Quotas" heading
    And the Brave credit bar should show "90" percent
    And the Brave card should show "4,500 / 5,000 USD"
    And the Brave USD value should carry "$4.5 left" hover text
    And the Brave card subtitle should contain "Reported by provider"
    And the Brave key balance shows "Brave work" and "$1,234.50 left"
    And the usage view should not show "USD left"
    And the usage view should not show "∞"
    And the usage view should not show "n/a"

  @stub @quota @parallel
  Scenario: Parallel without a card keeps an action slot and no invented balance
    Given the stubbed provider limits show "Brave finite credits"
    And the stubbed credit totals show "Brave no use"
    When I navigate directly to "/system/quotas"
    Then I should see the "Quotas" heading
    And the usage view should show "How credit units are priced"
    And the usage view should not show "∞"
    And the usage view should not show "Tier split unavailable"

  @stub @quota @manual
  Scenario: Brave manual entry opens a USD balance dialog from the card
    Given the stubbed provider limits show "Brave finite credits"
    And the stubbed credit totals show "Brave no use"
    When I navigate directly to "/system/quotas"
    And I open the credit manual entry for "brave"
    Then the manual entry should show "Credit mode"
    And the manual entry should show "Allowance (USD)"
    And the manual entry should show "Balance remaining (USD)"
    When I cancel the credit dialog
    Then the usage view should show "Brave"

  @stub @quota @oauth
  Scenario: Quotas directs Parallel pairing to Keys and pools
    Given the stubbed provider limits show "Brave finite credits plus Parallel card"
    And the stubbed credit totals show "Brave no use"
    When I navigate directly to "/system/quotas"
    Then I should see the "Quotas" heading
    And the usage view should show "Parallel"
    And the usage view offers no OAuth pairing control
    And Quotas links to Keys and pools for Parallel
    And the usage view should not show "∞"

  @stub @quota @keenable
  Scenario: Unknown credits render no invented bar or funds
    Given the stubbed provider limits show "Brave unknown credits"
    And the stubbed credit totals show "Brave no use"
    When I navigate directly to "/system/quotas"
    Then I should see the "Quotas" heading
    And the Brave card should show no credit bar
    And the usage view should not show "Unknown"
    And the usage view should not show "n/a"
    And the usage view should not show "∞"

  @stub @quota @tavily
  Scenario: Tavily native Credits render with Credits labels
    Given the stubbed provider limits show "Tavily finite credits"
    And the stubbed credit totals show "Tavily search and extract use"
    When I navigate directly to "/system/quotas"
    Then I should see the "Quotas" heading
    And the Tavily credit bar should show "100" percent
    And the Tavily card should show "1,000 / 1,000 Tavily credits"
    And the usage view should show "Native spend"
    And the usage view should show "1.2 Tavily credits"
    Given the stubbed session works in project Alpha
    When I open the "playground" section of project Alpha
    And I pin the playground provider to "Tavily"
    And I submit the playground search query "stubbed query"
    Then the search telemetry should show "Credits"

  @stub @quota @tavily
  Scenario: Tavily out-of-Credits 402 reaches the user at once
    Given the stubbed provider limits show "Tavily finite credits"
    And the stubbed credit totals show "Tavily no use"
    And the stubbed session works in project Alpha
    When I open the "playground" section of project Alpha
    And I pin the playground provider to "Tavily"
    And I submit the playground search query "tavily out of credits probe"
    Then the playground search error should show "Tavily is out of Credits. Wait until reset or upgrade."
