@control
Feature: Provider control plane and routing settings
  As a local FreeSearch operator
  I want to configure providers, secrets, and routing without network access
  So that runtime behavior is explicit and durable

  Scenario: Provider enumeration exposes canonical defaults
    Given an offline control API with stub adapters
    When I list the control-plane providers
    Then the control-plane provider list should contain the eight canonical providers
    And every provider should have a closed circuit breaker and no latency p95

  Scenario: Provider enablement patch persists to a fresh read
    Given an offline control API with stub adapters
    When I disable the "exa" provider through the control API
    Then the control-plane GET for "exa" should report enabled false
    And a fresh control-plane read should still report enabled false

  Scenario: Secret write is masked and delete removes the vault value
    Given an offline control API with an in-memory secret store
    When I write a secret for "exa" through the control API
    Then the secret response should be configured with a masked fingerprint
    When I delete the "exa" secret through the control API
    Then the secret response should report missing and contain no raw key

  Scenario: Routing policy GET and PUT round trip
    Given an offline control API with stub adapters
    When I update routing to first_only and free_first with 2 attempts
    Then the routing GET should equal first_only free_first and 2 attempts

  Scenario: Dashboard activity exposes measured latency and status
    Given an offline control API with stub adapters
    When I submit an offline control search
    Then the dashboard recent activity should contain a non-negative latency and success status

  Scenario: Failure telemetry survives a failed adapter request
    Given an offline control API with a failing adapter
    When I submit a failing offline control search
    Then the control request should return HTTP 500
    And stats and dashboard should show a failure usage row and degraded health

  Scenario Outline: Independent search and fetch choices drive adapter calls
    Given an offline control API with stub adapters and call counters
    When I apply the "<access_choice>" access choice to "exa"
    Then the control-plane GET for "exa" should report enable mask <enable_mask> and support mask 7
    When I submit offline search and fetch via REST
    Then the REST search provider should be "<search_provider>"
    And the REST fetch outcome should be "<fetch_outcome>"
    And the adapter call counts should be exa search <exa_search> fetch <exa_fetch> and brave search <brave_search> fetch <brave_fetch>
    And a fresh control-plane read for "exa" should still report enable mask <enable_mask>

    Examples:
      | access_choice | enable_mask | search_provider | fetch_outcome | exa_search | exa_fetch | brave_search | brave_fetch |
      | both-on       | 7           | exa             | succeed-exa   | 1          | 1         | 0            | 0           |
      | search-off    | 5           | brave           | succeed-exa   | 0          | 1         | 1            | 0           |
      | fetch-off     | 3           | exa             | fail-503      | 1          | 0         | 0            | 0           |
      | global-off    | 6           | brave           | fail-503      | 0          | 0         | 1            | 0           |

  Scenario: Global OFF preserves tool choices across ON transitions
    Given an offline control API with stub adapters and call counters
    When I apply the "search-off" access choice to "exa"
    And I apply the "global-off" access choice to "exa"
    Then the control-plane GET for "exa" should report enable mask 4 and support mask 7
    When I submit offline search and fetch via REST
    Then the REST search provider should be "brave"
    And the REST fetch outcome should be "fail-503"
    When I reset the adapter call counters
    And I apply the "global-on" access choice to "exa"
    Then the control-plane GET for "exa" should report enable mask 5 and support mask 7
    When I submit offline search and fetch via REST
    Then the REST search provider should be "brave"
    And the REST fetch outcome should be "succeed-exa"

  Scenario: Pure access predicate blocks unsupported tools
    Given an offline control API with stub adapters and call counters
    Then the pure access predicate should allow search but block fetch for enable 7 support 3
    And the pure access predicate should block search and fetch for enable 7 support 0
    And the pure access predicate should block search and fetch for enable 7 support 6

  Scenario: Unsupported Brave fetch is rejected
    Given an offline control API with stub adapters and call counters
    When I submit an offline fetch requiring provider "brave" via REST
    Then the REST fetch outcome should be "fail-503"
    And the adapter call counts should be exa search 0 fetch 0 and brave search 0 fetch 0

  Scenario: Explicit routing modes respect access masks
    Given an offline control API with stub adapters and call counters
    When I apply the "search-off" access choice to "exa"
    Then the control-plane GET for "exa" should report enable mask 5 and support mask 7
    When I submit an offline search requiring provider "exa" via REST
    Then the REST search should fail with 503 containing "no required provider is eligible"
    When I submit an offline search requiring provider "brave" via REST
    Then the REST search provider should be "brave"
    When I submit an offline search preferring provider "brave" via REST
    Then the REST search provider should be "brave"
    When I submit an offline auto search via REST
    Then the REST search provider should be "brave"

  Scenario: Scoped fanout respects access masks
    Given an offline control API with stub adapters and call counters
    When I apply the "search-off" access choice to "exa"
    When I submit an offline fanout search via REST
    Then the fanout participating providers should be "brave"
    When I submit an offline fanout search restricted to providers "exa" via REST
    Then the fanout search should fail with 503 containing "no eligible provider"
    When I submit an offline fanout search restricted to providers "exa, brave" via REST
    Then the fanout participating providers should be "brave"

  Scenario: REST and MCP observe the same stored choices
    Given an offline control API with stub adapters and call counters and an MCP server
    When I apply the "search-off" access choice to "exa"
    Then the control-plane GET for "exa" should report enable mask 5 and support mask 7
    When I submit offline search via REST
    Then the REST search provider should be "brave"
    When I call the MCP search tool
    Then the MCP search provider should be "brave"
    When I call the MCP fetch tool
    Then the MCP fetch provider should be "exa"

  Scenario: Mask change after MCP generation applies to the next request
    Given an offline control API with stub adapters and call counters and an MCP server
    When I call the MCP search tool
    Then the MCP search provider should be "exa"
    When I apply the "search-off" access choice to "exa"
    When I call the MCP search tool
    Then the MCP search provider should be "brave"
    And the adapter call counts should be exa search 1 fetch 0 and brave search 1 fetch 0
