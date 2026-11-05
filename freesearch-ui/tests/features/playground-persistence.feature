@stub
Feature: Playground persistence across navigation and reload
  Playground search/fetch drafts, mapped results, and execution status live
  in the persisted Redux slice of one project (U2: the key is
  freesearch:playground:v2:<account>:<project>): page switches inside the
  project must not refetch and reloads must rehydrate from localStorage
  without issuing new backend requests.

  Background:
    Given the stubbed session works in project Alpha
    When I open the "playground" section of project Alpha
    Then I should see the "Playground" heading

  Scenario: Search and fetch drafts with results survive navigation and reload without refetching
    Given the persisted playground state is cleared
    When I submit the playground search query "persistence probe query"
    Then the persisted search results should show "Live backend result one"
    When I open the playground tab "Fetch"
    And I submit the playground fetch URL "https://example.com/persisted-doc"
    Then the persisted fetch document should show "Parsed Markdown Document"
    When I follow the "Members" link of the Project navigation
    Then I should see the "Members" heading
    When I follow the "Playground" link of the Project navigation
    Then I should see the "Playground" heading
    And the persisted fetch URL should be "https://example.com/persisted-doc"
    And the persisted fetch document should show "Parsed Markdown Document"
    When I open the playground tab "Search"
    Then the persisted search draft should be "persistence probe query"
    And the persisted search results should show "Live backend result one"
    When I reload the page
    Then I should see the "Playground" heading
    And the persisted search draft should be "persistence probe query"
    And the persisted search results should show "Live backend result one"
    When I open the playground tab "Fetch"
    Then the persisted fetch URL should be "https://example.com/persisted-doc"
    And the persisted fetch document should show "Parsed Markdown Document"
    And the persisted search request count should be 1
    And the persisted fetch request count should be 1
    And the last search request should name project Alpha
    And the last fetch request should name project Alpha
    And the playground state should be persisted only under the project key of Alpha

  Scenario: Loading search survives a page switch without duplicate execution
    Given the persisted playground state is cleared
    When I hold the persisted search response
    And I submit the playground search query "deferred persistence query"
    Then the playground search button should read "Executing..."
    When I follow the "Members" link of the Project navigation
    Then I should see the "Members" heading
    When I follow the "Playground" link of the Project navigation
    Then I should see the "Playground" heading
    And the playground search button should read "Executing..."
    When I release the persisted search response
    Then the persisted search results should show "Live backend result one"
    And the persisted search request count should be 1

  Scenario: Search error survives navigation and reload without a new request
    Given the persisted playground state is cleared
    When I submit the playground search query "doomed query"
    Then the persisted search error should contain "stubbed provider unavailable"
    When I note the persisted search request count
    And I follow the "Members" link of the Project navigation
    Then I should see the "Members" heading
    When I follow the "Playground" link of the Project navigation
    Then I should see the "Playground" heading
    And the persisted search draft should be "doomed query"
    And the persisted search error should contain "stubbed provider unavailable"
    When I reload the page
    Then I should see the "Playground" heading
    And the persisted search draft should be "doomed query"
    And the persisted search error should contain "stubbed provider unavailable"
    And the persisted search request count should not have increased
