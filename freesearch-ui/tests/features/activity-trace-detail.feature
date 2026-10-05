@stub
Feature: Activity trace detail presentation parity with Playground
  The Activity trace Results tab converges toward the Playground presentation:
  one shared card and one shared inspector behind thin adapters. This parity
  scenario pins the Playground side of that contract through the stubbed
  backend: titles, URLs, two-line snippets, provider badges, scores, fetch
  and external-link actions, raw JSON inspection with copy feedback, a
  non-selectable execution waterfall, and the fetch metadata presentation.

  Background:
    Given I navigate to the web application

  @stub
  Scenario: Playground cards, inspector, and waterfall share one presentation
    When I select the "Playground" header tab
    And I pin the playground provider to "Brave Search"
    And I submit the playground search query "parity probe"
    Then the playground cards should show titles, urls, two-line snippets, badges, and scores
    And each playground card should keep fetch and external-link actions outside selection
    When I select the playground result "Live backend result one"
    Then the playground inspector should show the shared result presentation
    And the playground inspector link should carry the Open target URL tooltip
    And the playground waterfall should be non-selectable with latency and result counts
    When I expand the playground raw JSON inspector
    Then the playground raw JSON inspector should offer a copy action
    When I copy the playground raw JSON
    Then the playground raw JSON copy should confirm
    When I open the playground tab "Fetch"
    And I pin the playground fetch provider to "Keenable"
    And I submit the playground fetch URL "https://example.com/parity-doc"
    Then the playground fetch result should show metadata, provider badge, and copy action
    And the playground fetch result should show the catalog provider name "Keenable"
