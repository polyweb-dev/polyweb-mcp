@keenable-cr1 @stub
Feature: Keenable card shared bar
  One shared bar for funds use and rate use on the Keenable card only.
  Colors show remaining capacity. Counts show whole numbers.
  Keyless credits show a strike value next to free with no authoritative line.

  Background:
    Given I navigate to the web application

  @keenable-cr1 @stub @funds
  Scenario Outline: K09 Keenable keyed funds bar color at <remaining> capacity
    Given the Keenable card fixture uses "keyed" access with "<remaining>" capacity
    When I navigate directly to "/usage"
    Then the Keenable "funds" bar shows "<percent>" percent with "<color>" color

    Examples:
      | remaining | percent | color  |
      | 100000    | 100     | green  |
      | 75000     | 75      | yellow |
      | 50000     | 50      | yellow |
      | 25000     | 25      | orange |
      | 0         | 0       | red    |

  @keenable-cr1 @stub @rate
  Scenario Outline: K09 Keenable keyless rate bar color at <remaining> capacity
    Given the Keenable card fixture uses "keyless" access with "<remaining>" capacity
    When I navigate directly to "/usage"
    And I open the Keenable quota details
    Then the Keenable "search" bar shows "<percent>" percent with "<color>" color

    Examples:
      | remaining      | percent | color  |
      | 1000.00000000  | 100     | green  |
      | 750.00000000   | 75      | yellow |
      | 500.00000000   | 50      | yellow |
      | 250.00000000   | 25      | orange |
      | 0              | 0       | red    |

  @keenable-cr1 @stub @rows
  Scenario: K09 Keenable search and fetch rate rows share one hourly pool
    Given the Keenable card fixture uses "keyless" access with "1000.00000000" capacity
    When I navigate directly to "/usage"
    And I open the Keenable quota details
    Then the Keenable details should show "Search hourly rate"
    And the Keenable details should show "Fetch hourly rate"
    And the Keenable rate bar occupies a line below its text

  @keenable-cr1 @stub @counts
  Scenario: K10 Keenable request counts show whole numbers with strike free and no funds bar
    Given the Keenable card fixture uses "keyless" access with "1000.00000000" capacity
    When I navigate directly to "/usage"
    And I open the Keenable quota details
    Then the Keenable request counts contain no decimal part
    And the Keenable keyless value has a strike line next to free
    And the Keenable card should show no funds bar

  @keenable-cr1 @stub @confidence
  Scenario: K11 Keenable keyless details omit authoritative confidence with costs intact
    Given the Keenable card fixture uses "keyless" access with "1000.00000000" capacity
    When I navigate directly to "/usage"
    And I open the Keenable quota details
    Then the Keenable keyless details contain no authoritative label
    And the Keenable details should show "Search hourly rate"
    And the Keenable details should show "Fetch hourly rate"

  @keenable-cr1 @stub @actions
  Scenario: K09 Keenable actions and details control stay reachable with Escape return
    Given the Keenable card fixture uses "keyed" access with "100000" capacity
    When I navigate directly to "/usage"
    Then the Keenable card should show the "Sync" action
    And the Keenable card should show the "Budget Limit" action
    And the Keenable card should show the "History" action
    When I open the Keenable quota details
    Then the Keenable details should show "Search CRD cost"
    And the Keenable details should show "Fetch CRD cost"
    When I cancel the Keenable details
    Then the Keenable details control regains focus
