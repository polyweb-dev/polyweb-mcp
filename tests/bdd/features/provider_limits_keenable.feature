@limits
Feature: Keenable keyed and keyless limits through mock transport
  Keenable uses four catalog records and mock transport only.
  Each scenario names its plan ID for traceability to K01 through K07.
  No live keys and no vendor I/O occur in any scenario.

  Scenario: K01 Keenable catalog holds four records for keyed and keyless rails
    Given the Keenable catalog records
    Then Keenable holds four records for keyed and keyless search and fetch
    And Keenable keyless records hold no budget

  Scenario: K02 Keenable keyed search and fetch share one pool and one rate bucket
    Given the Keenable catalog records
    When I read the Keenable keyed pool contract
    Then Keenable keyed search and fetch share pool keenable:keyed:request with 10 per second and 100000 monthly

  Scenario: K03 Keenable keyless shares rate windows with no budget
    Given the Keenable catalog records
    When I read the Keenable keyless rate contract
    Then Keenable keyless search and fetch share 10 per second and 1000 per hour with no budget

  Scenario: K04 Keenable reported credits debit one shared pool
    Given a Keenable pool with full monthly funds
    When one Keenable search reports three credits and one fetch reports two credits
    Then the Keenable pool holds remaining 99995 with 399980 CRDs in both views
    And the Keenable totals hold costs 12 and 8 CRDs with one native debit per success

  Scenario: K05 Keenable paid usage stays separate and 402 keeps zero after rebuild
    Given a Keenable adapter with paid usage of two credits
    When Keenable answers 402 after paid usage
    Then the Keenable snapshot holds remaining zero with separate free and paid spend
    When I rebuild the Keenable adapter from stored rows
    Then the rebuilt Keenable snapshot still holds remaining zero

  Scenario: K06 Keenable 402 exhausts funds while 429 preserves funds
    Given a Keenable adapter with mock error answers
    When Keenable answers 429 with rate pressure
    Then the Keenable rate error stays retryable with no funds zero observation
    When Keenable answers 402 with exhaustion
    Then the Keenable funds error stays non-retryable with remaining zero

  Scenario: K07 Keenable shared views count funds once and totals count each attempt once
    Given a Keenable pool with full monthly funds
    When two Keenable keyed calls succeed with standard cost
    Then the Keenable shared views hold one pool with 399992 CRDs each
    And the Keenable totals count each attempt once with separate search and fetch rows

  Scenario: K03b Keenable keyless local denial makes zero vendor calls
    Given a Keenable keyless pool with exhausted shared windows
    When I request one Keenable keyless search
    Then the Keenable keyless gate denies with local 429 and zero vendor calls
