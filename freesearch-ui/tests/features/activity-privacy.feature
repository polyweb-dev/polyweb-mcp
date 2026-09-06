Feature: Private operational activity telemetry
  The activity view exposes operational metrics without disclosing request targets.

  Background:
    Given I navigate to the web application
    When I select the "Activity" header tab
    Then I should see the "Activity" heading

  @smoke
  Scenario: Show operational columns without query or URL values
    Then the activity table should expose only the columns "Time", "Operation", "Provider", "Status", "Latency", and "Cost"
    And the activity document should not contain seeded query or URL values
    And the activity page should not expose a "Clear log" button
