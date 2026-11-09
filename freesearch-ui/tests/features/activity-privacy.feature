Feature: Private operational activity telemetry
  The activity view exposes operational metrics without disclosing request targets.
  Against the live backend the ledger may be empty, so the suite accepts the
  columns view or the empty state.

  Activity is a project section: the run selects the project named by
  FREESEARCH_E2E_PROJECT (default "Local E2E").

  Background:
    Given I navigate to the web application
    When I open the projects list
    And I choose the live e2e project in the project selector
    And I follow the "Activity" link of the Project navigation
    Then I should see the "Activity" heading

  @smoke
  Scenario: Show operational columns without query or URL values
    Then the activity view should show telemetry columns or an empty state
    And the activity document should not contain seeded query or URL values
    And the activity page should not expose a "Clear log" button
