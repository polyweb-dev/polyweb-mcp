@monitoring
Feature: Read-only monitoring API (JSON for the future React dashboard)
  As a local FreeSearch operator
  I want to inspect observed usage, quota, and health telemetry
  So that I can diagnose providers without exposing request payloads

  Scenario: REST search and fetch usage appears in stats and dashboard JSON
    Given an offline monitoring repository and REST adapters
    When I submit REST search query "stage four search" and fetch URL "https://example.com/stage-four"
    Then REST telemetry should contain search and fetch totals for their providers
    And REST recent usage should be newest first
    And REST quota entries should expose their source
    And REST stats and dashboard JSON should show the local-observed notice

  Scenario: MCP search and fetch record the same telemetry as REST
    Given an offline monitoring repository and MCP adapters
    When I call the MCP search and fetch tools
    Then MCP telemetry should contain the same usage and health records

  Scenario: Monitoring displays never expose request content or secrets
    Given an offline monitoring repository and a privacy-safe REST adapter
    When I submit a private REST search and fetch request
    Then telemetry metadata should contain numeric values only
    And stats and dashboard JSON should not contain request content or secrets

  Scenario: Telemetry repository failures do not fail a user request
    Given a REST app with a failing telemetry repository
    When I submit a resilient REST search request
    Then the REST request should succeed despite telemetry failure
