@monitoring @observability
Feature: OpenTelemetry trace observability for search and fetch
  As a local Polyweb operator
  I want search and fetch requests recorded as queryable traces
  So that I can inspect inputs, results, stage latencies, and errors from Activity

  # @monitoring keeps these scenarios offline: the harness skips live adapter
  # construction and every provider interaction uses stubs or MockTransport.

  Scenario: Successful search records a full trace with matching trace header
    Given an offline trace repository with a mock-transport Keenable search
    And the system policy explicitly permits full trace capture
    When I submit a traced search for "distributed consensus algorithms" with limit 10
    Then the traced search should succeed with provider "keenable" and 2 results
    And the traced response should carry a trace header matching 32 lowercase hex chars
    And the trace list should contain exactly 1 trace matching the trace header
    And the trace detail should show the full query "distributed consensus algorithms" with 2 normalized results
    And the search trace detail should show the required search span hierarchy with non-negative durations
    And the stored trace should contain no secret values

  Scenario: Provider exception keeps the HTTP failure while recording an error trace
    Given an offline trace repository with a failing search provider
    When I submit a traced search for "unreachable query" with limit 5
    Then the traced search should fail with status 500 and no fabricated results
    And the trace list should contain exactly 1 trace with outcome "error"
    And the error trace detail should show root and provider ERROR with error type "RuntimeError"
    And the error trace detail should contain exactly one exception event

  Scenario: Fanout with one failing provider records sibling spans and partial outcome
    Given an offline trace repository with one failing and one succeeding fanout provider
    When I submit a traced fanout search for "fusion probe" with limit 10
    Then the traced fanout search should succeed with the surviving provider results
    And the fanout trace detail should show one root with 2 sibling provider spans
    And the fanout trace detail should show outcome "partial" with the failed provider in ERROR
    And the fanout trace detail should show sibling provider spans with identities "flaky" and "reliable"

  Scenario: Monitoring reads and trace reads create no additional traces
    Given an offline trace repository with a mock-transport Keenable search
    When I submit a traced search for "trace count probe" with limit 1
    And I read the dashboard, stats, and trace endpoints
    Then the trace list should still contain exactly 1 trace
    And an unknown trace id should return 404 without creating a trace

  Scenario: Fetch mirrors search tracing for success and error
    Given an offline trace repository with a mock-transport Keenable fetch
    And the system policy explicitly permits full trace capture
    When I submit a traced fetch for "https://example.com/article"
    Then the traced fetch should succeed with the stubbed document content
    And the fetch trace detail should show the required fetch span hierarchy with non-negative durations
    When I submit a traced fetch for "https://example.com/boom" against a failing provider
    Then the traced fetch should fail with status 500 and an error trace with error type "RuntimeError"

  Scenario: Trace roots carry the exact account UUID
    Given an offline trace repository with a mock-transport Keenable search
    When I submit a traced search for "owned query" with limit 1
    Then the trace detail should carry my account UUID
    And the trace list rows should carry my account UUID

  Scenario: Each project reads only its own traces
    Given an offline trace repository with a mock-transport Keenable search
    When I submit a traced search for "alice query" with limit 1
    And I register a second trace reader
    And I submit a traced search for "bob query" with limit 1 as the second reader
    Then each reader should list only its own trace
    And a foreign trace read should return 404 like an absent trace
