@limits @s1
Feature: Brave keyed search credits through synthetic headers
  S1 Brave uses two keyed records and mock headers only.
  Each scenario names its BDD ID for traceability to PLAN revision 6.
  No live keys and no vendor I/O occur in any scenario.

  Scenario: B01 S1 Brave catalog holds 2 keyed records and no keyless rail
    Given the Brave catalog records
    Then Brave holds one keyed search record and one keyed fetch placeholder
    And Brave holds no keyless record

  Scenario: B06 Brave USD 5 converts to 5000 CRDs at 5 per search
    Given the Brave catalog records
    When I project the Brave priced balance
    Then USD 5 gives 5000 CRDs and one standard search costs 5 CRDs

  Scenario: B34 Brave monthly headers feed the USD budget only
    Given a Brave adapter with monthly headers of 900 left of 1000
    When I read the Brave usage snapshot
    Then the Brave pool holds allowance 5.000 USD with remaining 4.500 USD
    And the Brave observation carries no hour bar and no day bar

  Scenario: B06 Brave manual USD 5 anchor gives 5000 estimated CRDs
    Given a Brave adapter with no vendor headers
    When I anchor Brave manual funds of USD 5
    Then the Brave manual pool projects 5000 estimated CRDs

  Scenario: B10 Brave card shows finite search with n/a fetch and no fetch grant
    Given a Brave app with seeded catalog and monthly headers of 900 left of 1000
    When I read the Brave provider view
    Then the Brave search view is finite with cost 5 and the fetch view is unavailable
    And a Brave fetch grant fails with 422

  Scenario: B11 Brave zero funds deny with local 402 and zero vendor calls
    Given a Brave pool with zero USD funds
    When I request one Brave search
    Then the Brave gate denies with local 402 and zero vendor calls

  Scenario: B15 Brave budget 429 never retries while rate 429 retries
    Given a Brave adapter with mock error answers
    When Brave answers 429 with QUOTA_LIMITED
    Then the Brave error is quota_exhausted with one attempt and no retry
    When Brave answers 429 with RATE_LIMITED
    Then the Brave error is retryable with three attempts

  Scenario: B19 Brave detail shows native USD plan reset rates source and link
    Given a Brave app with seeded catalog and monthly headers of 900 left of 1000
    When I read the Brave provider detail
    Then the Brave detail shows native USD plan reset rates source and link

  Scenario: B20 Brave grant period persists with audit old new source
    Given a Brave pool with known USD funds
    When I save a Brave search grant for one period
    Then the Brave grant period persists with audit old new source

  Scenario: B21 Brave CRD values keep route order identical
    Given Brave route fixtures with different CRD values
    When I select Brave routes twice
    Then the Brave route order and fallback stay identical

  Scenario: B26 Brave fetch stays n/a and never unknown or zero
    Given the Brave catalog records
    When I project the Brave fetch view
    Then the Brave fetch state is unavailable and never unknown Free or zero

  Scenario: B27 Brave paid funds admit the call
    Given a Brave pool with known USD funds
    When I request one Brave search
    Then the Brave gate admits the call

  Scenario: B39 Brave totals count each attempt once
    Given a Brave pool with known USD funds
    When two Brave searches succeed
    Then the Brave totals hold one row with exact normalized CRDs and two attempts

  Scenario: B41 Brave simultaneous denials keep 402 precedence with zero vendor calls
    Given a Brave pool with zero USD funds and an exhausted burst window
    When I request one Brave search
    Then the Brave denial keeps both reasons with 402 precedence and zero vendor calls
