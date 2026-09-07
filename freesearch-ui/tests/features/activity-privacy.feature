Feature: Private operational activity telemetry
  The activity view exposes operational metrics without disclosing request targets.
  Against the live backend the ledger may be empty, so the suite accepts the
  columns view or the empty state.

  Background:
    Given I navigate to the web application
    When I select the "Activity" header tab
    Then I should see the "Activity" heading

  @smoke
  Scenario: Show operational columns without query or URL values
    Then the activity view should show telemetry columns or an empty state
    And the activity document should not contain seeded query or URL values
    And the activity page should not expose a "Clear log" button
