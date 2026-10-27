@limits @s0
Feature: Core CRD contracts and gates through synthetic services
  S0 core uses zero catalog records and synthetic adapters.
  Each scenario names its BDD ID for traceability to PLAN revision 6.

  Scenario: B01 S0 core catalog holds zero records and empty views
    Given an empty synthetic limit catalog
    When I read the synthetic dashboard views
    Then the synthetic catalog holds 0 records
    And the synthetic dashboard views are empty

  Scenario: B04 one lease owner coordinates shared sync
    Given an empty synthetic limit catalog
    When two synthetic sync claimants race for one provider
    Then one synthetic claimant owns the sync lease

  Scenario: B05 bad usage payload preserves last balance as stale
    Given a synthetic finite pool with known balance
    When a bad synthetic usage payload arrives
    Then the synthetic last balance survives as stale

  Scenario: B06 K 0.001 converts priced native use to exact CRDs
    Given an empty synthetic limit catalog
    When I project synthetic priced balances
    Then USD 0.001 gives one CRD and USD 0.002 gives two
    And standard search costs are five for 0.005 and seven for 0.007
    And a Turbo fetch costs one CRD

  Scenario: B11 exact 0.58 cannot cover exact 0.599
    Given a synthetic finite pool with 0.58 CRDs and cost 0.599
    When I request one synthetic call
    Then the synthetic gate denies with local 402 and zero vendor calls

  Scenario: B12 concurrent fractional reservations never overspend
    Given a synthetic finite pool with 1.0 CRDs and cost 0.6
    When two synthetic calls race for admission
    Then one synthetic admission succeeds and balances never go negative

  Scenario: B13 definite failure releases reservation with zero debit
    Given a synthetic admitted call with reserved capacity
    When the synthetic vendor fails definitely
    Then the synthetic reservation releases with zero CRD debit

  Scenario: B19 detail exposes native balance USD plan reset rates source and link
    Given a synthetic finite pool with known balance
    When I read the synthetic provider detail
    Then the synthetic detail shows native USD plan reset rates source and link

  Scenario: B20 grant period persists with old new source audit
    Given a synthetic finite pool with known balance
    When I save a synthetic grant for one period
    Then the synthetic grant period persists with audit old new source

  Scenario: B21 different CRD values keep route order identical
    Given synthetic route fixtures with different CRD values
    When I select routes twice
    Then the synthetic route order and fallback stay identical

  Scenario: B22 one denied provider keeps candidates and fuses others
    Given two synthetic providers with one denied by funds
    When I run synthetic fanout admission
    Then the synthetic candidates stay unchanged and the live result fuses

  Scenario: B23 rotated secret rejects the stale sync response
    Given a synthetic finite pool with known balance
    When the synthetic credential rotates then the old response arrives
    Then the synthetic stale response is rejected

  Scenario: B24 one schedule task per generation closes cleanly
    Given an empty synthetic limit catalog
    When I start and stop the synthetic sync task
    Then one synthetic task runs per generation and closes cleanly

  Scenario: B25 url_count greater than one is rejected before vendor IO
    Given an empty synthetic limit catalog
    When I submit a synthetic fetch with url_count 2
    Then the synthetic fetch is rejected with 422 and zero vendor calls

  Scenario: B26 unknown price never becomes zero Free or n-a
    Given a synthetic unpriced finite record with no balance
    When I project the synthetic CRD view
    Then the synthetic state is unknown and never zero Free or n-a

  Scenario: B27 free zero with paid capacity permits execution
    Given a synthetic unmetered rail and a synthetic finite pool with funds
    When I request one synthetic call on each rail
    Then both synthetic rails admit the call

  Scenario: B33 malformed rate observation preserves unknown state
    Given an empty synthetic limit catalog
    When a malformed synthetic rate observation arrives
    Then the synthetic rate state stays unknown without denial

  Scenario: B37 positive funds with exhausted hour rate gives 429 not 402
    Given a synthetic finite pool with funds and an exhausted hour window
    When I request one synthetic call
    Then the synthetic gate denies with local 429 and Retry-After

  Scenario: B38 rate reset refills rate and budget reset refills pool
    Given a synthetic finite pool with an exhausted hour window
    When the synthetic hour passes and a budget refill arrives
    Then the synthetic rate refills without moving funds and the pool refills

  Scenario: B39 shared views contribute funds once and totals count once
    Given one synthetic shared pool with search and fetch views
    When I project the synthetic shared views and totals
    Then the synthetic funds count once and totals count each attempt once

  Scenario: B40 price version change preserves historical audit values
    Given a synthetic finite pool with known balance
    When the synthetic price version changes after a debit
    Then the synthetic audit keeps the original price version

  Scenario: B41 simultaneous denials keep both reasons with 402 precedence
    Given a synthetic finite pool with zero funds and an exhausted hour window
    When I request one synthetic call
    Then the synthetic denial keeps both reasons with 402 precedence and zero vendor calls
