@stub
Feature: Playground persistence across navigation and reload
  Playground search/fetch drafts, mapped results, and execution status live
  in the persisted Redux slice: page switches must not refetch and reloads
  must rehydrate from localStorage without issuing new backend requests.

  Background:
    Given I navigate to the web application
    When I navigate directly to "/playground"

  Scenario: Search and fetch drafts with results survive navigation and reload without refetching
    Given the persisted playground state is cleared
    When I submit the playground search query "persistence probe query"
    Then the persisted search results should show "Live backend result one"
    When I open the playground tab "Fetch"
    And I submit the playground fetch URL "https://example.com/persisted-doc"
    Then the persisted fetch document should show "Parsed Markdown Document"
    When I follow the "Routing" sidebar link
    Then I should see the "Routing" heading
    When I follow the "Playground" sidebar link
    Then I should see the "Search Playground" heading
    And the persisted fetch URL should be "https://example.com/persisted-doc"
    And the persisted fetch document should show "Parsed Markdown Document"
    When I open the playground tab "Search"
    Then the persisted search draft should be "persistence probe query"
    And the persisted search results should show "Live backend result one"
    When I reload the page
    Then I should see the "Search Playground" heading
    And the persisted search draft should be "persistence probe query"
    And the persisted search results should show "Live backend result one"
    When I open the playground tab "Fetch"
    Then the persisted fetch URL should be "https://example.com/persisted-doc"
    And the persisted fetch document should show "Parsed Markdown Document"
    And the persisted search request count should be 1
    And the persisted fetch request count should be 1

  Scenario: Loading search survives a page switch without duplicate execution
    Given the persisted playground state is cleared
    When I hold the persisted search response
    And I submit the playground search query "deferred persistence query"
    Then the playground search button should read "Executing..."
    When I follow the "Routing" sidebar link
    Then I should see the "Routing" heading
    When I follow the "Playground" sidebar link
    Then I should see the "Search Playground" heading
    And the playground search button should read "Executing..."
    When I release the persisted search response
    Then the persisted search results should show "Live backend result one"
    And the persisted search request count should be 1

  Scenario: Search error survives navigation and reload without a new request
    Given the persisted playground state is cleared
    When I submit the playground search query "doomed query"
    Then the persisted search error should contain "stubbed provider unavailable"
    When I note the persisted search request count
    And I follow the "Routing" sidebar link
    Then I should see the "Routing" heading
    When I follow the "Playground" sidebar link
    Then I should see the "Search Playground" heading
    And the persisted search draft should be "doomed query"
    And the persisted search error should contain "stubbed provider unavailable"
    When I reload the page
    Then I should see the "Search Playground" heading
    And the persisted search draft should be "doomed query"
    And the persisted search error should contain "stubbed provider unavailable"
    And the persisted search request count should not have increased
