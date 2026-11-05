@latency
Feature: FreeSearch routing latency with instant provider adapters
  As an agent calling FreeSearch instead of a provider directly
  I want the server-side time FreeSearch adds on top of each provider to stay under 150 ms at p95
  So that searching and fetching through FreeSearch is not noticeably slower

  # Runs in the default suite. Real REST and MCP servers are served by uvicorn
  # on 127.0.0.1 with OS-assigned ports and called over TCP; every provider is
  # backed by an instant fake adapter that mirrors the real capability flags.
  # Gated value: server-side added = server_ms - provider_ms, where server_ms
  # runs from the request reaching the FreeSearch app until its response is
  # sent. Client wall time, client overhead (wall - server), and database reads
  # per request are reported only. Reports: test_reports/routing_latency_offline.
  # {csv,md}; FREESEARCH_LATENCY_PROFILE=1 adds per-transport pyinstrument profiles.

  Background:
    Given the routing latency servers are running with instant fake adapters for every provider

  Scenario Outline: Warm <operation> pinned to <provider> over <transport> adds under 150 ms server-side at p95
    When I send warm <operation> requests pinned to "<provider>" over <transport>
    Then every measured <operation> request is served by "<provider>"
    And the p95 server-side FreeSearch-added latency is under 150 ms
    And database reads per request are reported

    Examples: REST
      | transport | operation | provider  |
      | rest      | search    | brave     |
      | rest      | search    | exa       |
      | rest      | search    | firecrawl |
      | rest      | search    | keenable  |
      | rest      | search    | parallel  |
      | rest      | search    | tavily    |
      | rest      | search    | tinyfish  |
      | rest      | search    | you       |
      | rest      | fetch     | brave     |
      | rest      | fetch     | exa       |
      | rest      | fetch     | firecrawl |
      | rest      | fetch     | keenable  |
      | rest      | fetch     | parallel  |
      | rest      | fetch     | tavily    |
      | rest      | fetch     | tinyfish  |
      | rest      | fetch     | you       |

    Examples: MCP
      | transport | operation | provider  |
      | mcp       | search    | brave     |
      | mcp       | search    | exa       |
      | mcp       | search    | firecrawl |
      | mcp       | search    | keenable  |
      | mcp       | search    | parallel  |
      | mcp       | search    | tavily    |
      | mcp       | search    | tinyfish  |
      | mcp       | search    | you       |
      | mcp       | fetch     | brave     |
      | mcp       | fetch     | exa       |
      | mcp       | fetch     | firecrawl |
      | mcp       | fetch     | keenable  |
      | mcp       | fetch     | parallel  |
      | mcp       | fetch     | tavily    |
      | mcp       | fetch     | tinyfish  |
      | mcp       | fetch     | you       |
