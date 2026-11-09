@quota
Feature: Quota and usage accounting (QUOTA.md acceptance)
  As a Polyweb operator
  I want quota snapshots and usage totals with honest units and confidence
  So that the dashboard and routing never mix requests, credits, and dollars

  # AC-1 — Persistence pipeline: bounded TTL/on-demand polling reaches record_quota.
  @ac1
  Scenario: Quota-capable providers persist snapshots through a bounded poll
    Given an isolated quota repository
    When the bounded quota poll runs for every quota-capable provider
    Then every valid poll result should reach record_quota
    And no populated provider should report an empty latest_quota
    And the poll should reuse cached snapshots within its TTL instead of polling every request

  # AC-2 — Brave observed monthly REQUEST quota from comma-pair headers.
  @ac2
  Scenario: Brave monthly quota comes from the second element of comma-pair headers
    Given an isolated quota repository
    And a Brave adapter with stubbed headers "11, 1000" remaining, "60, 15000" limit, "5, 2592000" reset
    When I run a successful Brave search for "quota headers" with limit 3
    Then the Brave snapshot should be OBSERVED monthly REQUEST quota with remaining 1000 limit 15000
    And the Brave snapshot reset should be about 2592000 seconds after observation
    And the Brave usage event should carry unit kind REQUEST

  @ac2
  Scenario Outline: Brave malformed monthly elements fall back to the local counter, never zero
    Given an isolated quota repository
    And a Brave adapter with stubbed headers "<remaining>" remaining, "<limit>" limit, "<reset>" reset
    When I run a successful Brave search for "quota headers" with limit 3
    Then the Brave snapshot should be a <source> monthly counter with remaining <counter_remaining> of limit <counter_limit>

    Examples:
      | remaining | limit  | reset | counter_remaining | counter_limit | source    |
      | 11        | 60     | 5     | 999               | 1000          | ESTIMATED |
      | 11,       | 60, 9  | 5, 7  | 8                 | 9             | OBSERVED  |
      | 11, -4    | 60, 9  | 5, 7  | 8                 | 9             | OBSERVED  |
      | 11, 1000  | 60     | 5, 7  | 999               | 1000          | ESTIMATED |
      | 11, 1000  | 60, -2 | 5, 7  | 999               | 1000          | ESTIMATED |

  @ac2
  Scenario Outline: Brave malformed reset elements stay unknown, never zero
    Given an isolated quota repository
    And a Brave adapter with stubbed headers "<remaining>" remaining, "<limit>" limit, "<reset>" reset
    When I run a successful Brave search for "quota headers" with limit 3
    Then the Brave snapshot monthly field "reset" should be unknown rather than zero

    Examples:
      | remaining | limit | reset  |
      | 11, 1000  | 60, 9 | 5      |
      | 11, 1000  | 60, 9 | 5, -30 |

  # AC-3 — Safe aggregation by (provider, operation, unit_kind), FAILURE exclusion.
  @ac3
  Scenario: Usage totals group by provider, operation, and unit kind
    Given an isolated quota repository
    And usage events with incompatible dimensions recorded
    When I read usage totals
    Then totals should group by provider, operation, and unit kind without cross-kind sums
    And zero-unit FAILURE rows should be excluded from totals

  # AC-4 — Tavily authoritative CREDIT; You.com estimated floored calls, limit None.
  @ac4
  Scenario: Tavily usage stays authoritative CREDIT quota
    Given an isolated quota repository
    When I record an authoritative Tavily credit snapshot with remaining 42 limit 1000
    Then the Tavily snapshot should expose unit kind CREDIT with display unit "credits" and source AUTHORITATIVE
    And the Tavily usage event should carry unit kind CREDIT

  @ac4
  Scenario Outline: You.com balance cents persist as a USD balance with call equivalents
    Given an isolated quota repository
    When I convert You.com balance <balance_cents> cents
    Then the remaining balance should be USD <balance_usd> with <search_calls> search calls and <fetch_calls> fetch calls, limit unknown

    Examples:
      | balance_cents | balance_usd | search_calls | fetch_calls |
      | 100           | 1.00        | 200          | 1000        |
      | 101           | 1.01        | 202          | 1010        |
      | 1             | 0.01        | 2            | 10          |
      | 0             | 0           | 0            | 0           |

  @ac4
  Scenario: You.com partial cents never buy a fractional call
    Given an isolated quota repository
    When I convert You.com balance 2 cents
    Then the remaining balance should be USD 0.02 with 4 search calls and 20 fetch calls, limit unknown

  @ac4
  Scenario: You.com missing response usage is an explicit gap, not a silent zero
    Given an isolated quota repository
    When I record a You.com response with missing usage
    Then the event should be marked metering-unavailable rather than known-zero USD
    And usage_gap should stay off the wire

  # AC-5 — Keenable/Parallel local counters.
  @ac5
  Scenario: Keenable keyed allowance decrements locally while keyless tracks hourly requests
    Given an isolated quota repository
    When I apply 3 paid-false Keenable calls against the 100000 monthly allowance
    Then the Keenable remaining should be 99997 of 100000
    And a paid-true Keenable call should preserve the free allowance separately
    And a keyless Keenable call should record one REQUEST unit and an hourly snapshot

  @ac5
  Scenario: Keenable keyed estimate prices one request at about USD 0.004
    Given an isolated quota repository
    When I estimate cost for a Keenable search
    Then the Keenable estimate should be USD 0.004

  @ac5
  Scenario: Parallel search and extract estimates are mode-aware Decimal USD
    Given an isolated quota repository
    When I estimate Parallel search in "turbo" mode with 0 extra bundles
    Then the Parallel search estimate should be USD 0.001
    When I estimate Parallel search in "advanced" mode with 2 extra bundles
    Then the Parallel search estimate should be USD 0.007
    When I estimate Parallel search with omitted mode and 0 extra bundles
    Then the Parallel search estimate should be USD 0.005
    When I estimate Parallel extract for 4 urls
    Then the Parallel extract estimate should be USD 0.004 as a projection-only batch price
    And the executable single-URL extract estimate should be USD 0.001

  # AC-6 — Routing: hard steers away, soft expires on success, 429 transient, unknown not zero.
  @ac6
  Scenario: Routing steers away from hard exhaustion but forgives Parallel soft signals
    Given an isolated quota repository
    When I route a search with a hard-exhausted provider and healthy fallback
    Then the hard-exhausted provider should be excluded from candidates
    When the Parallel soft zero is followed by a successful billed operation
    Then the Parallel provider should be eligible again
    When a provider reports a 429 rate signal
    Then the 429 should never become quota exhaustion
    When a provider has no quota snapshot at all
    Then unknown quota should stay eligible and never masquerade as zero

  # AC-7 — Backend serialization exposes unit_kind/display_unit/source.
  @ac7
  Scenario: Quota and usage payloads serialize unit kind, display unit, and source
    Given an isolated quota repository
    When I serialize a quota snapshot and a usage event with canonical units
    Then the serialized quota should expose unit_kind, display_unit, and source
    And the serialized usage should expose unit_kind and display_unit

  # AC-8 — Additive/nullable compat, no credentials in metadata, bounded polling.
  @ac8
  Scenario: Legacy rows without unit kinds remain readable as unknown
    Given an isolated quota repository
    When I record legacy usage and quota rows without unit kinds
    Then legacy rows should read back with unknown unit kind and stay out of known-kind totals

  @ac8
  Scenario: Usage metadata never persists credentials or request content
    Given an isolated quota repository
    When I record usage metadata containing credential keys
    Then the metadata write should be rejected without persisting secrets

  @ac8
  Scenario: Vendor quota polling is bounded and never per request
    Given an isolated quota repository
    When the bounded quota poll runs twice in quick succession
    Then the vendor should be called at most once within the TTL window

  # AC-3/AC-8 — mixed known-kind and legacy rows stay separated, never merged.
  @ac3 @ac8
  Scenario: Mixed known-kind and legacy usage stay separated in totals
    Given an isolated quota repository
    And known-kind and legacy usage events recorded together
    When I read usage totals
    Then known-kind totals should stay Decimal-exact
    And legacy rows should appear only in legacy-compatible totals

  # AC-8 — quota metadata round-trip through the public API only.
  # NOTE: quota metadata persistence needs explicit schema-plan approval;
  # this scenario asserts behaviorally via latest_quota, never private columns.
  @ac8
  Scenario: Quota snapshot metadata survives a public round-trip
    Given an isolated quota repository
    When I record a quota snapshot carrying routing metadata
    Then latest_quota should return the same metadata

  # AC-1/AC-8 — poll failure-safety: a bad write must not break poll or routing.
  @ac1 @ac8
  Scenario: A failing quota write never breaks the poll or routing
    Given an isolated quota repository
    When the bounded quota poll runs with a failing record_quota
    Then the poll should still return the healthy providers' snapshots
    And routing should still produce candidates from available state

  # AC-FC — Firecrawl authoritative credit polling and estimates.
  @firecrawl @ac-fc
  Scenario: Firecrawl quota maps remaining truth, plan baseline, and billing reset
    Given an isolated quota repository
    When I map a Firecrawl credit-usage payload with remaining 250, plan 100, and a billing end
    Then the Firecrawl snapshot should be AUTHORITATIVE CREDIT with remaining 250 limit 100
    And the Firecrawl reset should match the billing period end

  @firecrawl @ac-fc
  Scenario Outline: Firecrawl malformed credit fields are rejected safely
    Given an isolated quota repository
    When I map a Firecrawl credit-usage payload with remaining "<remaining>" and plan "<plan>"
    Then the Firecrawl snapshot field "<field>" should be unknown rather than zero

    Examples:
      | remaining | plan | field     |
      | NaN       | 100  | remaining |
      | Infinity  | 100  | remaining |
      | -5        | 100  | remaining |
      | 250       | NaN  | limit     |

  @firecrawl @ac-fc
  Scenario Outline: Firecrawl estimates match executed fetch options
    Given an isolated quota repository
    When I estimate Firecrawl search with limit <limit>
    Then the Firecrawl search estimate should be <credits> credits
    When I estimate Firecrawl fetch with <pdf> pdf pages, json extract <json>, enhanced <enhanced>, retention <zdr>
    Then the Firecrawl fetch estimate should be <fetch_credits> credits

    Examples:
      | limit | credits | pdf | json  | enhanced | zdr   | fetch_credits |
      | 10    | 2       | 0   | false | false    | false | 1             |
      | 11    | 4       | 2   | false | false    | false | 3             |
      | 25    | 6       | 0   | true  | false    | false | 5             |
      | 10    | 2       | 0   | false | true     | true  | 2             |

  # AC-PA — Parallel raw SKU retention, spend ledger, no API-key balance poll.
  @parallel @ac-pa
  Scenario: Parallel keeps raw SKU counts and prices spend in Decimal USD
    Given an isolated quota repository
    When I record a Parallel search response with SKU counts 1 and 2
    Then the Parallel usage units should be 3 with SKU metadata retained
    And the Parallel spend projection should be Decimal USD, never float

  @parallel @ac-pa
  Scenario: Parallel free-seed budget is opt-in and failure-aware
    Given an isolated quota repository
    When I enable the Parallel USD 5.00 monthly seed and record USD 1.25 of successful spend
    Then the Parallel remaining should be USD 3.75 of USD 5.00
    When a Parallel 402 soft signal arrives
    Then the Parallel remaining should read soft zero without a hard lockout
    When a later Parallel billed operation succeeds
    Then the Parallel soft zero should be cleared
    When a Parallel 429 transient signal arrives
    Then the Parallel 429 should never become quota exhaustion

  @parallel @ac-pa
  Scenario: Parallel capabilities stay quota-false with no API-key balance poll
    Given an isolated quota repository
    When I inspect Parallel quota capabilities
    Then Parallel capabilities quota should stay false
    And no API-key poll of the OAuth balance endpoint should be attempted

  @parallel @ac-pa
  Scenario: Unseeded Parallel accounts track spend without a fabricated balance
    Given an isolated quota repository
    When I record Parallel spend without enabling the free seed
    Then the Parallel quota should report remaining unknown with limit unknown

  # AC-EXA — Exa spend ledger, pricing fallback, manual credits, exhaustion-aware
  @exa @ac-exa
  Scenario: Exa monthly budget is opt-in and exhaustion-aware
    Given an isolated quota repository
    When I enable the Exa USD 10.00 monthly budget and record USD 0.007 of successful spend
    Then the Exa remaining should be USD 9.993 of USD 10.00
    When an Exa 402 exhaustion signal arrives
    Then the Exa remaining should read observed zero
    When a later Exa billed operation succeeds
    Then the Exa exhaustion should be cleared
    When an Exa 429 exhaustion signal arrives
    Then the Exa 429 should surface observed zero

  @exa @ac-exa
  Scenario: Exa capabilities report quota with local snapshots and no balance poll
    Given an isolated quota repository
    When I inspect Exa quota capabilities
    Then Exa capabilities quota should read true

  @exa @ac-exa
  Scenario: Unbudgeted Exa accounts track spend without a fabricated balance
    Given an isolated quota repository
    When I record Exa spend without enabling the monthly budget
    Then the Exa quota should report remaining unknown with limit unknown

  @exa @ac-exa
  Scenario: Exa fallback pricing values untelemetered spend into the monthly sum
    Given an isolated quota repository
    When I run an Exa search with 3 results and no cost telemetry
    Then the Exa usage should carry fallback estimate USD 0.007
    When I run an Exa metered search costing USD 0.005
    And I hydrate the Exa monthly ledger against a USD 10.00 budget
    Then the Exa remaining should be USD 9.988 of USD 10.00

  @exa @ac-exa
  Scenario: Exa manual starting credits anchor remaining spend
    Given an isolated quota repository
    When I set Exa manual starting credits to USD 5.00 and record USD 0.007 of spend
    Then the Exa remaining should be USD 4.993 of USD 5.00


  # B-QUOTA-BRAVE-REGRESSION — degenerate 0/0 is unknown and routable (AC-2/AC-6).
  @quota @ac2
  Scenario: Brave degenerate zero limit is treated as unknown and stays routable
    Given an isolated quota repository
    And a Brave adapter with stubbed headers ", 0" remaining, ", 0" limit, ", 0" reset
    When I run a successful Brave search for "open data documentation" with limit 3
    Then the Brave snapshot remaining should be unknown and limit should be unknown and reset should be unknown
    And Brave should stay eligible for search routing despite zero monthly elements

  @quota @ac2
  Scenario: Brave missing monthly elements fall back to the local counter and stay routable
    Given an isolated quota repository
    And a Brave adapter with stubbed headers "11" remaining, "60" limit, "5" reset
    When I run a successful Brave search for "open data documentation" with limit 3
    Then the Brave snapshot should be a ESTIMATED monthly counter with remaining 999 of limit 1000
    And the Brave snapshot limit should be flagged as implied
    And Brave should stay eligible for search routing with counter headroom

  @quota @ac2
  Scenario: Brave monthly counter resets at the billing boundary
    Given an isolated quota repository
    And a Brave adapter with stubbed headers "11" remaining, "60" limit, "5" reset
    When I run a successful Brave search for "quota headers" with limit 3
    And I run a successful Brave search for "quota headers" with limit 3
    Then the Brave snapshot should be a ESTIMATED monthly counter with remaining 998 of limit 1000
    When the billing month rolls over
    And I run a successful Brave search for "quota headers" with limit 3
    Then the Brave snapshot should be a ESTIMATED monthly counter with remaining 999 of limit 1000

  @quota @ac2
  Scenario: Brave genuine zero remaining with positive limit stays excluded
    Given an isolated quota repository
    And a Brave adapter with stubbed headers "1, 0" remaining, "60, 1000" limit, "5, 2592000" reset
    When I run a successful Brave search for "open data documentation" with limit 3
    Then the Brave snapshot should be OBSERVED monthly REQUEST quota with remaining 0 limit 1000
    And Brave should be excluded from search routing when remaining is zero with a known positive limit

  # S4 — shared normalize_degenerate_quota through BOTH read paths (AC-2/AC-6).
  # Direct record_quota of Brave OBSERVED REQUEST 0/0 (bypassing the adapter's
  # own zero-limit guard) must still normalize on the dashboard path
  # (_latest_quotas/collect_stats) exactly like effective_quota, and routing
  # must stay eligible. RED until polyweb.monitoring.normalize_degenerate_quota
  # exists and is used by BOTH paths.
  @quota @ac2
  Scenario: Degenerate zero-limit quota normalizes through both read paths and stays routable
    Given an isolated quota repository
    When I record a Brave OBSERVED REQUEST quota with remaining 0 limit 0
    Then collect_stats latest_quota for brave should be unknown remaining limit and reset
    And effective_quota for brave should match the normalized unknown view
    And Brave should stay eligible from the normalized view despite zero limit

  @quota @ac6
  Scenario: Keyless rolling-hour local zero stays routable because the pool is shared
    Given an isolated quota repository
    When I record a keyless local hourly quota at zero remaining
    Then keyless local hourly zero should stay eligible for routing

  # Brave derived USD spend: manual dashboard math ($5.00 per 1000 requests).
  # 176 REQUEST successes project to $0.88 spend metadata alongside the $5
  # allowance, while the unlimited throttle stays None/None with no percent
  # and per-second headroom stays in usage metadata.
  @quota @ac2
  Scenario: Brave derived spend tracks REQUEST successes without touching throttle
    Given an isolated quota repository
    And a Brave adapter with stubbed headers "49, 0" remaining, "50, 0" limit, "1, 0" reset
    When I record 175 successful Brave REQUEST searches
    And I run a successful Brave search for "spend projection" with limit 3
    Then collect_stats Brave quota should show spend USD 0.88 of allowance USD 5.00 at cost USD 0.005 per request
    And the Brave snapshot remaining should be unknown and limit should be unknown and reset should be unknown
    And the Brave usage event should carry per-second headroom 49
