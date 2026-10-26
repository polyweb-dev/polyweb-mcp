@live @latency
Feature: FreeSearch routing latency against live providers
  As a FreeSearch operator preparing a release
  I want each real provider's time reported separately from the server-side time FreeSearch adds
  So that I can prove FreeSearch adds under 80 ms at p95 on top of every live provider

  # Opt-in only: the default behave run excludes @live (pyproject
  # [tool.behave] default_tags). Run with:
  #   uv run behave --tags="@live and @latency"
  # Each provider runs only when its harness env key is set (FREESEARCH_*_API_KEY,
  # TINYFISH_API_KEY); keyless Keenable runs only with FREESEARCH_RUN_LIVE=1.
  # Otherwise the scenario is skipped with a reason naming the env var, never
  # its value. Sample counts default to 1 warmup + 5 measured requests per row,
  # overridable with FREESEARCH_LATENCY_LIVE_WARMUP and
  # FREESEARCH_LATENCY_LIVE_SAMPLES. Reports are written to
  # test_reports/routing_latency_live.{csv,md}. Gated value: server-side added =
  # server_ms - provider_ms (request reaching the FreeSearch app until its
  # response is sent, minus the adapter call); client overhead is reported only.

  Scenario Outline: Live warm <operation> pinned to <provider> over <transport> reports provider and FreeSearch time
    Given the live "<provider>" adapter is enabled by the harness env for <operation> over <transport>
    And the routing latency servers are running with live adapters
    When I send warm <operation> requests pinned to "<provider>" over <transport>
    Then every measured <operation> request is served by "<provider>"
    And provider time and server-side FreeSearch-added time are reported separately
    And the p95 server-side FreeSearch-added latency is under 80 ms

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
