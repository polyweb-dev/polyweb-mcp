@tinyfish @offline
Feature: Tinyfish Provider Adapter Integration
  As an AI agent search and fetch consumer
  I want to query the Tinyfish provider offline using mocked transport
  So that I can verify normalized search results, markdown extractions, error mappings, and resilience without external network dependencies

  @search @results
  Scenario: Successful search returns normalized results and latency metrics
    Given the Tinyfish adapter is configured with a valid API key
    And a mocked offline Tinyfish transport returning search results
    When I perform a Tinyfish search for "open data documentation" with limit 2
    Then the Tinyfish search response should use provider "tinyfish"
    And the Tinyfish search response should contain normalized results
    And each Tinyfish result should have a non-empty title, url, and snippet
    And the Tinyfish search response should report correct total count
    And the Tinyfish search response should report one request unit
    And the Tinyfish search operation should report non-negative latency metrics
    And the Tinyfish request should include the X-API-Key header
    And no live external network calls should be made

  @fetch @markdown
  Scenario: Successful fetch extracts clean markdown and document metadata
    Given the Tinyfish adapter is configured with a valid API key
    And a mocked offline Tinyfish transport returning markdown document extraction
    When I perform a Tinyfish fetch for "https://example.com/docs" with max 1000 chars
    Then the Tinyfish fetch response should use provider "tinyfish"
    And the Tinyfish fetch response should contain clean markdown content
    And the Tinyfish fetch document should contain metadata with final_url and language
    And the Tinyfish fetch response should report one request unit
    And the Tinyfish request should include the X-API-Key header
    And no live external network calls should be made

  @auth @error @401
  Scenario: Authentication error 401 fails fast and maps to invalid_api_key
    Given the Tinyfish adapter is configured with a valid API key
    And the Tinyfish API returns a 401 unauthorized error
    When I perform a Tinyfish search for "open data documentation" with limit 2
    Then the Tinyfish operation should fail with "invalid_api_key"
    And the Tinyfish error should not be retryable
    And the Tinyfish error status code should be 401
    And no live external network calls should be made

  @ratelimit @error @429
  Scenario: Rate limit error 429 maps to rate_limited and marks operation retryable
    Given the Tinyfish adapter is configured with a valid API key
    And the Tinyfish API returns a 429 rate limit error
    When I perform a Tinyfish search for "open data documentation" with limit 2
    Then the Tinyfish operation should fail with "rate_limited"
    And the Tinyfish error should be retryable
    And the Tinyfish error status code should be 429
    And no live external network calls should be made

  @auth @failclosed
  Scenario: Missing API key fails closed with configuration_error before network egress
    Given the Tinyfish adapter has no API key configured
    When I attempt to initialize the Tinyfish adapter without an API key
    Then the Tinyfish initialization should fail closed with configuration_error
    And the Tinyfish error should not be retryable
    And no live external network calls should be made

  @transport @offline @mock
  Scenario: Strict offline transport mocking intercepts all requests with zero network egress
    Given the Tinyfish adapter is configured with a valid API key
    And a mocked offline Tinyfish transport
    When I perform a Tinyfish search for "network isolation test" with limit 1
    Then the Tinyfish wire request should target "api.search.tinyfish.ai"
    And the Tinyfish wire request should use the GET method
    And the Tinyfish request should include the X-API-Key header
    And no live external network calls should be made
