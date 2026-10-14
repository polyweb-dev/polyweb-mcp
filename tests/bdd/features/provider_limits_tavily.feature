@limits @tavily
Feature: Tavily keyed Credits through synthetic headers
  TAV Tavily uses two keyed records and two keyless rails with mock headers only.
  Each scenario names its BDD ID for traceability to PLAN revision 6.
  No live keys and no vendor I/O occur in any scenario.

  Scenario: T01 Tavily catalog holds 2 keyed records and 2 keyless rails on one shared bucket
    Given the Tavily catalog records
    Then Tavily holds one keyed search record and one keyed extract record
    And Tavily holds two keyless rails with unpublished rate and no budget
    And Tavily shares one default minute bucket across search and extract

  Scenario: T02 Tavily dev bucket mixes search and extract to 100 then denies 101 without vendor I/O
    Given a Tavily dev pool with 1000 Credits remaining
    When I mix Tavily search and extract to 100 attempts
    Then the Tavily 101st attempt denies with local 429 and zero vendor calls

  Scenario: T03 Tavily concurrent mixed operations share one bucket
    Given a Tavily dev pool with 1000 Credits remaining
    When concurrent Tavily search and extract admissions race on one bucket
    Then one Tavily admission succeeds and balances never go negative

  Scenario: T04 Tavily prod bucket mixes search and extract to 1000 then denies 1001 without vendor I/O
    Given a Tavily prod pool with 10000 Credits remaining
    When I mix Tavily search and extract to 1000 attempts
    Then the Tavily 1001st attempt denies with local 429 and zero vendor calls

  Scenario: T05 Tavily key environment switches dev 100 to prod 1000
    Given the Tavily catalog records
    When I apply Tavily key environment prod
    Then both Tavily keyed records carry limit 1000 on the shared bucket
    When I apply Tavily key environment dev
    Then both Tavily keyed records carry limit 100 on the shared bucket

  Scenario: T06 Tavily keyless header carries access mode with no key through the real SDK
    Given Tavily keyed and keyless adapters over MockTransport with ambient key set
    When I run Tavily search and extract on both rails through the real SDK
    Then the Tavily keyless wire carries X-Tavily-Access-Mode keyless with no key and no ambient leak
    And the Tavily keyed wire carries Bearer with key precedence when both headers exist

  Scenario: T07 Tavily full params ride identically on both auth rails
    Given Tavily keyed and keyless adapters with recording SDKs
    When I send Tavily full search and extract params on both rails
    Then both Tavily rails forward identical search depth topic domains answer content images country and extract depth format query chunks images
    And a Tavily explicit depth conflict denies before vendor I/O

  Scenario: T08 Tavily search debits basic 1 and advanced 2 Credits
    Given a Tavily dev pool with 1000 Credits remaining
    When I estimate Tavily basic and advanced search cost
    Then Tavily basic search costs 1 Credit and advanced search costs 2 Credits
    When one Tavily basic search and one Tavily advanced search succeed
    Then the Tavily pool debits exactly 3 Credits with local projections and no usage GET

  Scenario Outline: T09 Tavily extract debits <good_urls> good URLs at <depth> depth cost <expected_credits> Credits
    Given a Tavily dev pool with 1000 Credits remaining
    When one Tavily <depth> extract succeeds with <good_urls> good URLs
    Then the Tavily extract debit is <expected_credits> Credits

    Examples:
      | depth    | good_urls | expected_credits |
      | basic    | 0         | 0                |
      | basic    | 1         | 0.2              |
      | basic    | 4         | 0.8              |
      | basic    | 5         | 1                |
      | basic    | 6         | 1.2              |
      | advanced | 0         | 0                |
      | advanced | 1         | 0.4              |
      | advanced | 4         | 1.6              |
      | advanced | 5         | 2                |
      | advanced | 6         | 2.4              |

  Scenario: T10 Tavily mixed good and bad URLs debit only good URLs with failed calls at zero
    Given a Tavily dev pool with 1000 Credits remaining
    When one Tavily basic extract succeeds with 3 good and 2 bad URLs
    Then the Tavily extract debit is 0.6 Credits
    When one Tavily call fails definitely
    Then the Tavily reservation releases with zero Credit debit
    When one Tavily extract succeeds with empty valid documents
    Then the Tavily extract debit is 0 Credits

  Scenario: T11 Tavily absent malformed and reported-zero usage stay exact
    Given a Tavily adapter with stub usage payloads
    When Tavily usage omits all figures
    Then the Tavily observation stays unknown with no invented debit
    When Tavily usage reports malformed figures
    Then the Tavily usage raises invalid_response with no secret leak
    When Tavily usage reports zero remaining of 1000
    Then the Tavily observation keeps reported zero with allowance 1000

  Scenario: T12 Tavily monthly reset fires on day 1 including December to January
    Given a Tavily dev pool with 0 Credits remaining in March
    When the Tavily clock reaches 2026-04-01
    Then the Tavily free pool refills to 1000 Credits with a reset audit
    When the Tavily clock reaches 2027-01-01 from December
    Then the Tavily free pool refills to 1000 Credits with a reset audit

  Scenario Outline: T13 Tavily free zero unknown PAYGO key-cap and spend-cap gate exact
    Given a Tavily dev pool with 1000 Credits remaining
    When the Tavily funds state is "<state>"
    Then the Tavily gate decision is "<decision>" with status <status>

    Examples:
      | state           | decision | status |
      | free_zero       | deny     | 402    |
      | unknown         | admit    | 200    |
      | paygo_overage   | admit    | 200    |
      | vendor_key_cap  | deny     | 402    |
      | local_spend_cap | deny     | 402    |

  Scenario: T14 Tavily shared pool shows both operation views with grant history route and debit
    Given a Tavily app with seeded catalog and 1000 Credits pool
    When I read the Tavily provider view
    Then the Tavily search view is finite with cost 1 and the extract view is finite with cost 0.2
    And both Tavily operation views share one pool without double funds
    When I save a Tavily search grant for one period
    Then the Tavily grant period persists with audit old new source
    When I select Tavily routes twice
    Then the Tavily route order and fallback stay identical
    When two Tavily searches succeed
    Then the Tavily totals hold exact Credits with two attempts

  Scenario: T15 Tavily async poll adds no delay with zero route cost budget GETs
    Given a Tavily adapter with held usage GET and seeded pool
    When Tavily search and extract run while the usage poll is held
    Then Tavily search and extract finish before the poll releases
    And Tavily route cost and budget reads issue zero usage GETs

  Scenario: T16 Tavily cadence 59.999 versus 60 with same-owner two schedulers and force sync
    Given a Tavily pool with a claimed sync lease at fixed time
    When a second Tavily sync claims at plus 59.999 seconds
    Then the Tavily second claim is held
    When a third Tavily sync claims at plus 60 seconds with an expired lease
    Then the Tavily third claim succeeds with next sync 60 seconds later
    When two Tavily schedulers race and one owner forces sync twice
    Then one Tavily scheduler owns the lease and force cannot bypass cadence

  Scenario: T17 Tavily poll failure stale restart key change and old poll guards hold
    Given a Tavily pool with known Credits and a due sync
    When the Tavily poll fails with transport error
    Then the Tavily last balance survives as stale with no immediate retry
    When the Tavily runtime restarts and the key changes
    Then the Tavily terminal state clears and stale reads reject old polls
    When an old Tavily poll arrives after a newer 402 and local debits
    Then the Tavily old poll cannot replace the newer 402 or debits

  Scenario: T18 Tavily stale cache with vendor 402 through REST keeps one attempt zero debit and 402 text
    Given a Tavily REST app with stale positive cache and vendor 402
    When I request one Tavily search through REST
    Then the Tavily REST answer is HTTP 402 out of Credits with one vendor attempt and zero debit

  Scenario: T19 Tavily stale cache with vendor 402 through MCP keeps one attempt zero debit and 402 text
    Given a Tavily MCP app with stale positive cache and vendor 402
    When I request one Tavily search through MCP
    Then the Tavily MCP answer is 402 out of Credits with one vendor attempt and zero debit

  Scenario: T20 Tavily fanout holds other task with terminal 402 then local denial
    Given a Tavily fanout app with a held other task and vendor 402
    When I run Tavily fanout search with client fallback enabled
    Then the Tavily fanout held answer is terminal 402 with the other task cancelled
    And the Tavily fanout released answer fuses other success with local denial and no new vendor attempt
    And the Tavily single fallback answer is a local 402 with no new vendor attempt

  Scenario: T21 Tavily 429 then success sleeps exact Retry-After on both operations
    Given a Tavily adapter with 429 then success and recording sleeper
    When Tavily search retries after Retry-After 7
    Then the Tavily search sleeps exactly 7.0 with two vendor attempts
    When Tavily extract retries after Retry-After 3
    Then the Tavily extract sleeps exactly 3.0 with two vendor attempts

  Scenario Outline: T22 Tavily Retry-After variants keep exact backoff contract
    Given a Tavily adapter with recording sleeper and base delay 1.0
    When Tavily answers 429 with Retry-After "<header>"
    Then the Tavily retry sleep is "<sleeps>" with vendor attempts <attempts>

    Examples:
      | header                | sleeps | attempts |
      | absent                | 1.0    | 2        |
      | malformed             | 1.0    | 2        |
      | zero                  | 0.0    | 2        |
      | http-date             | 7.0    | 2        |
