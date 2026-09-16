@control
Feature: Provider control plane and routing settings
  As a local FreeSearch operator
  I want to configure providers, secrets, and routing without network access
  So that runtime behavior is explicit and durable

  Scenario: Provider enumeration exposes canonical defaults
    Given an offline control API with stub adapters
    When I list the control-plane providers
    Then the control-plane provider list should contain the seven canonical providers
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
