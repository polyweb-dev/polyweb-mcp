Feature: Provider and playground workflows

  Background:
    Given I navigate to the web application
  @smoke @live
  Scenario: Submit a playground search against the live backend
    When I open the projects list
    And I choose the live e2e project in the project selector
    And I follow the "Playground" link of the Project navigation
    And I submit the playground search query "distributed systems benchmarks"
    Then the playground should show search results or an error banner
    And the playground should not show multi-hop fallback text

  @stub
  Scenario: Tavily card tier slot shows compact labels beside buttons with no numeric rate text
    Given the sidebar session belongs to a system administrator
    And the Tavily stored key environment is "dev"
    And the stubbed provider limits show "Tavily finite credits"
    When I navigate directly to "/system/quotas"
    Then I should see the "Quotas" heading
    And the Tavily card tier slot should sit beside the card buttons
    And the Tavily card tier options should be compact without numeric rate text
    And the Tavily card rate tier should show "dev"
    And the Tavily card should contain no outside rate text
    And the Tavily card should show one credit bar
    And the Tavily Credits should still show "1,000"
    And no Tavily rate tier PATCH should exist
    And no Tavily usage requests should exist
    And no Tavily provider test requests should exist
    And no Tavily force-sync requests should exist

  @stub
  Scenario: Tavily card tier changes from dev to prod without reload with immediate confirmed ceiling
    Given the sidebar session belongs to a system administrator
    And the Tavily stored key environment is "dev"
    And the stubbed provider limits show "Tavily finite credits"
    When I navigate directly to "/system/quotas"
    Then I should see the "Quotas" heading
    When I open the credit details for "Tavily"
    Then the Tavily rate row should show "Search and fetch rate limit 100 requests per minute"
    When I choose the Tavily card rate tier "prod"
    Then exactly one Tavily rate tier PATCH should carry "prod"
    And the Tavily rate row should show "Search and fetch rate limit Limit 1,000 requests per minute"
    And the Tavily card should contain no outside rate text
    Given the stubbed provider limits show "Tavily prod credits"
    When I reload the web application
    And I select the "Quotas" header tab
    When I open the credit details for "Tavily"
    Then the Tavily rate row should show "Search and fetch rate limit 1,000 requests per minute"
    And the Tavily card should contain no outside rate text
    And the Tavily Credits should still show "1,000"
    And no Tavily usage requests should exist
    And no Tavily provider test requests should exist
    And no Tavily force-sync requests should exist

  @stub
  Scenario: Tavily card tier changes from prod to dev without reload with immediate confirmed ceiling
    Given the sidebar session belongs to a system administrator
    And the Tavily stored key environment is "prod"
    And the stubbed provider limits show "Tavily prod credits"
    When I navigate directly to "/system/quotas"
    Then I should see the "Quotas" heading
    When I open the credit details for "Tavily"
    Then the Tavily rate row should show "Search and fetch rate limit 1,000 requests per minute"
    When I choose the Tavily card rate tier "dev"
    Then exactly one Tavily rate tier PATCH should carry "dev"
    And the Tavily rate row should show "Search and fetch rate limit Limit 100 requests per minute"
    And the Tavily card should contain no outside rate text
    Given the stubbed provider limits show "Tavily finite credits"
    When I reload the web application
    And I select the "Quotas" header tab
    When I open the credit details for "Tavily"
    Then the Tavily rate row should show "Search and fetch rate limit 100 requests per minute"
    And the Tavily card should contain no outside rate text
    And the Tavily Credits should still show "1,000"
    And no Tavily usage requests should exist
    And no Tavily provider test requests should exist
    And no Tavily force-sync requests should exist

  @stub
  Scenario: Tavily card tier keeps the confirmed ceiling while the dashboard refresh is deferred
    Given the sidebar session belongs to a system administrator
    And the Tavily stored key environment is "dev"
    And the stubbed provider limits show "Tavily finite credits"
    And the Tavily dashboard refresh is held for 2000 milliseconds
    When I navigate directly to "/system/quotas"
    Then I should see the "Quotas" heading
    When I open the credit details for "Tavily"
    Then the Tavily rate row should show "Search and fetch rate limit 100 requests per minute"
    When I choose the Tavily card rate tier "prod"
    Then exactly one Tavily rate tier PATCH should carry "prod"
    And the Tavily rate row should show "Search and fetch rate limit Limit 1,000 requests per minute"
    And the Tavily card should contain no outside rate text
    And no Tavily usage requests should exist
    And no Tavily provider test requests should exist
    And no Tavily force-sync requests should exist

  @stub
  Scenario: Tavily card tier keeps zero PATCH writes for an unchanged selection
    Given the sidebar session belongs to a system administrator
    And the Tavily stored key environment is "dev"
    And the stubbed provider limits show "Tavily finite credits"
    When I navigate directly to "/system/quotas"
    Then I should see the "Quotas" heading
    And the Tavily card rate tier should show "dev"
    When I choose the Tavily card rate tier "dev"
    Then no Tavily rate tier PATCH should exist
    And the Tavily card rate tier should show "dev"
    And no Tavily usage requests should exist
    And no Tavily provider test requests should exist
    And no Tavily force-sync requests should exist

  @stub
  Scenario: Tavily card tier with invalid state shows Unknown lock and sends no PATCH
    Given the sidebar session belongs to a system administrator
    And the Tavily stored key environment is invalid
    And the stubbed provider limits show "Tavily finite credits"
    When I navigate directly to "/system/quotas"
    Then I should see the "Quotas" heading
    And the Tavily card rate tier should lock to Unknown
    And no Tavily rate tier PATCH should exist
    And no Tavily usage requests should exist
    And no Tavily provider test requests should exist
    And no Tavily force-sync requests should exist

  @stub
  Scenario: Tavily card tier with absent state shows Unknown lock and sends no PATCH
    Given the sidebar session belongs to a system administrator
    And the Tavily stored key environment is absent
    And the stubbed provider limits show "Tavily finite credits"
    When I navigate directly to "/system/quotas"
    Then I should see the "Quotas" heading
    And the Tavily card rate tier should lock to Unknown
    And no Tavily rate tier PATCH should exist
    And no Tavily usage requests should exist
    And no Tavily provider test requests should exist
    And no Tavily force-sync requests should exist

  @stub
  Scenario: Tavily card tier with read-only settings access shows compact text and sends no PATCH
    Given the sidebar session belongs to the "settings reader" account
    And the Tavily stored key environment is "dev"
    And the stubbed provider limits show "Tavily finite credits"
    When I navigate directly to "/system/quotas"
    Then I should see the "Quotas" heading
    And the Tavily card read-only rate text should show "Development"
    And the Tavily card should contain no outside rate text
    And no Tavily rate tier PATCH should exist
    And no Tavily usage requests should exist
    And no Tavily provider test requests should exist
    And no Tavily force-sync requests should exist

  @stub
  Scenario: Tavily card tier with keyless access shows compact text and sends no PATCH
    Given the sidebar session belongs to a system administrator
    And the Tavily key is keyless
    And the stubbed provider limits show "Tavily keyless credits"
    When I navigate directly to "/system/quotas"
    Then I should see the "Quotas" heading
    And the Tavily card keyless rate text should show "Keyless access"
    And the Tavily card should contain no outside rate text
    And no Tavily rate tier PATCH should exist
    And no Tavily usage requests should exist
    And no Tavily provider test requests should exist
    And no Tavily force-sync requests should exist

  @stub
  Scenario: Tavily card tier PATCH rejection keeps the stored value
    Given the sidebar session belongs to a system administrator
    And the Tavily stored key environment is "dev"
    And the stubbed provider limits show "Tavily finite credits"
    And the provider PATCH for "Tavily" will fail with "db down"
    When I navigate directly to "/system/quotas"
    Then I should see the "Quotas" heading
    And the Tavily card rate tier should show "dev"
    When I choose the Tavily card rate tier "prod"
    Then an inline Tavily card rate tier error should show "db down"
    And no Tavily usage requests should exist
    And no Tavily provider test requests should exist
    And no Tavily force-sync requests should exist

  @stub
  Scenario: Tavily card tier with missing PATCH readback shows Confirmation unavailable
    Given the sidebar session belongs to a system administrator
    And the Tavily stored key environment is "dev"
    And the stubbed provider limits show "Tavily finite credits"
    And the Tavily provider PATCH readback will be missing
    When I navigate directly to "/system/quotas"
    Then I should see the "Quotas" heading
    When the Tavily providers refresh will fail with "status down"
    And I choose the Tavily card rate tier "prod"
    Then exactly one Tavily rate tier PATCH should carry "prod"
    And a Tavily card confirmation unavailable note should show
    And the Tavily card rate tier should lock to Unknown
    And no Tavily usage requests should exist
    And no Tavily provider test requests should exist
    And no Tavily force-sync requests should exist

  @stub
  Scenario: Tavily card tier disables the select while a delayed PATCH is pending
    Given the sidebar session belongs to a system administrator
    And the Tavily stored key environment is "dev"
    And the stubbed provider limits show "Tavily finite credits"
    And the Tavily rate tier PATCH is delayed by 1500 milliseconds
    When I navigate directly to "/system/quotas"
    Then I should see the "Quotas" heading
    And the Tavily card rate tier should show "dev"
    When I choose the Tavily card rate tier "prod"
    Then the Tavily card rate tier should be disabled while pending
    And exactly one Tavily rate tier PATCH should carry "prod"
    And the Tavily card rate tier should show "prod"
    And no Tavily usage requests should exist
    And no Tavily provider test requests should exist
    And no Tavily force-sync requests should exist

  @stub
  Scenario: Tavily card tier ignores a PATCH response after unmount
    Given the sidebar session belongs to a system administrator
    And the Tavily stored key environment is "dev"
    And the stubbed provider limits show "Tavily finite credits"
    And the Tavily rate tier PATCH is delayed by 1200 milliseconds
    When I navigate directly to "/system/quotas"
    Then I should see the "Quotas" heading
    And the Tavily card rate tier should show "dev"
    When I choose the Tavily card rate tier "prod"
    And I select the "Providers" header tab
    Then I should see the "Providers" heading
    And exactly one Tavily rate tier PATCH should carry "prod"
    And no Tavily usage requests should exist
    And no Tavily provider test requests should exist
    And no Tavily force-sync requests should exist

  @stub
  Scenario: Tavily card tier converges after credential replacement during a delayed PATCH
    Given the sidebar session belongs to a system administrator
    And the Tavily stored key environment is "dev"
    And the stubbed provider limits show "Tavily finite credits"
    And the Tavily rate tier PATCH is delayed by 1200 milliseconds
    When I navigate directly to "/system/quotas"
    Then I should see the "Quotas" heading
    And the Tavily card rate tier should show "dev"
    When I choose the Tavily card rate tier "prod"
    And the Tavily key becomes keyless before the PATCH settles
    Then exactly one Tavily rate tier PATCH should carry "prod"
    When I reload the web application
    And I select the "Quotas" header tab
    Then the Tavily card keyless rate text should show "Keyless access"
    And no Tavily usage requests should exist
    And no Tavily provider test requests should exist
    And no Tavily force-sync requests should exist

  @stub
  Scenario: Tavily card tier keeps the saved value when refresh fails after save
    Given the sidebar session belongs to a system administrator
    And the Tavily stored key environment is "dev"
    And the stubbed provider limits show "Tavily finite credits"
    When I navigate directly to "/system/quotas"
    Then I should see the "Quotas" heading
    And the Tavily card rate tier should show "dev"
    When the Tavily dashboard refresh will fail with "dashboard down"
    And I choose the Tavily card rate tier "prod"
    Then exactly one Tavily rate tier PATCH should carry "prod"
    And the Tavily card rate tier should show "prod"
    And no Tavily usage requests should exist
    And no Tavily provider test requests should exist
    And no Tavily force-sync requests should exist

  @stub
  Scenario: Tavily card tier keeps keyboard access with a delayed PATCH
    Given the sidebar session belongs to a system administrator
    And the Tavily stored key environment is "dev"
    And the stubbed provider limits show "Tavily finite credits"
    When I navigate directly to "/system/quotas"
    Then I should see the "Quotas" heading
    When I focus the Tavily card rate tier select
    And I choose the Tavily card rate tier with the keyboard
    Then exactly one Tavily rate tier PATCH should carry "prod"
    And the Tavily card rate tier should show "prod"
    And no Tavily usage requests should exist
    And no Tavily provider test requests should exist
    And no Tavily force-sync requests should exist

  @stub
  Scenario: Tavily card quota details keep Escape and focus return at a narrow viewport
    Given I use a narrow viewport
    And the sidebar session belongs to a system administrator
    And the Tavily stored key environment is "dev"
    And the stubbed provider limits show "Tavily finite credits"
    When I navigate directly to "/system/quotas"
    Then I should see the "Quotas" heading
    And the Tavily card should contain no outside rate text
    When I open the Tavily quota details with the keyboard
    Then the Tavily rate row should show "Search and fetch rate limit 100 requests per minute"
    When I cancel the Tavily quota details
    Then the Tavily quota details should be closed
    And the Tavily details control regains focus
    And the Tavily card should contain no outside rate text
    And the document should have no horizontal overflow
    And no Tavily rate tier PATCH should exist
    And no Tavily usage requests should exist
    And no Tavily provider test requests should exist
    And no Tavily force-sync requests should exist

  @stub
  Scenario: Tavily card quota details show consumed dev headroom without a PATCH
    Given the sidebar session belongs to a system administrator
    And the Tavily stored key environment is "dev"
    And the Tavily dashboard shows consumed dev headroom
    When I navigate directly to "/system/quotas"
    Then I should see the "Quotas" heading
    And the Tavily card should contain no outside rate text
    When I open the credit details for "Tavily"
    Then the Tavily rate row should show "Search and fetch rate limit 90/100 requests per minute"
    And the Tavily Credits should still show "1,000"
    And no Tavily rate tier PATCH should exist
    And no Tavily usage requests should exist
    And no Tavily provider test requests should exist
    And no Tavily force-sync requests should exist

  @stub
  Scenario: Tavily card quota details show consumed prod headroom without a PATCH
    Given the sidebar session belongs to a system administrator
    And the Tavily stored key environment is "prod"
    And the Tavily dashboard shows consumed prod headroom
    When I navigate directly to "/system/quotas"
    Then I should see the "Quotas" heading
    And the Tavily card should contain no outside rate text
    When I open the credit details for "Tavily"
    Then the Tavily rate row should show "Search and fetch rate limit 900/1,000 requests per minute"
    And the Tavily Credits should still show "1,000"
    And no Tavily rate tier PATCH should exist
    And no Tavily usage requests should exist
    And no Tavily provider test requests should exist
    And no Tavily force-sync requests should exist
