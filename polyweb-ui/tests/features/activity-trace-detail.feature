@stub
Feature: Activity trace detail presentation parity with Playground
  The Activity trace Results tab converges toward the Playground presentation:
  one shared card and one shared inspector behind thin adapters. This parity
  scenario pins the Playground side of that contract through the stubbed
  backend: titles, URLs, two-line snippets, provider badges, scores, fetch
  and external-link actions, a non-selectable execution waterfall, and the
  fetch metadata presentation. A second scenario opens View details, the
  popup with the project trace inspector.

  Background:
    Given the stubbed session works in project Alpha

  @stub
  Scenario: Playground cards, inspector, and waterfall share one presentation
    When I open the "playground" section of project Alpha
    And I pin the playground provider to "Brave Search"
    And I submit the playground search query "parity probe"
    Then the playground cards should show titles, urls, two-line snippets, badges, and scores
    And each playground card should keep fetch and external-link actions outside selection
    When I select the playground result "Live backend result one"
    Then the playground inspector should show the shared result presentation
    And the playground inspector link should carry the Open target URL tooltip
    And the playground waterfall should be non-selectable with latency and result counts
    And the playground should offer View details instead of raw JSON
    When I open the playground tab "Fetch"
    And I pin the playground fetch provider to "Keenable"
    And I submit the playground fetch URL "https://example.com/parity-doc"
    Then the playground fetch result should show metadata, provider badge, and copy action
    And the playground fetch result should show the catalog provider name "Keenable"

  # TASK-000002: View details opens the project trace inspector for the call.
  # Auto routing keeps it independent of the provider picker.
  @stub
  Scenario: Playground View details opens the project trace inspector
    When I open the "playground" section of project Alpha
    And I submit the playground search query "view details probe"
    Then the playground should offer View details instead of raw JSON
    When I open the playground View details
    Then the playground trace detail popup should show the project trace
    When I close the playground trace detail popup
    Then the playground results should still show "Live backend result one"
