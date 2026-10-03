Feature: Activity trace list and disclosed detail
  The Activity list stays scannable and payload-free; the full query, the
  normalized results, and the stage timeline appear only after the user
  explicitly opens a trace. Error traces disclose the failure and the failed
  stage instead of fabricated results.

  Background:
    Given I navigate to the web application
    When I select the "Activity" header tab
    Then I should see the "Activity" heading

  @stub
  Scenario: Trace list stays payload-free and scannable
    Then the activity table should expose the columns "Time", "Operation", "Provider", "Status", "Latency", and "Results" with a "Details" action column
    And the activity list should not contain the disclosed query or result URLs
    And each activity row should expose a "View details" button

  @stub
  Scenario: Search detail discloses the query and normalized results
    When I open the "View details" control in row 1
    Then the trace detail dialog should be visible
    And the trace detail summary should show status "success" and provider "Keenable"
    And the trace detail should show the query "distributed consensus algorithms"
    And the trace detail should show result "https://docs.freesearch.dev/consensus" with title "Consensus algorithms explained"
    And the stage timeline should list 7 stages with durations
    And the "Technical details" disclosure should start "collapsed"

  @stub
  Scenario: Error fetch detail shows the failure and the failed stage
    When I open the "View details" control in row 2
    Then the trace detail dialog should be visible
    And the trace detail should show an error "http_error: HTTP 502"
    And the trace detail should show the fetched url "https://docs.freesearch.dev/getting-started"
    And the trace detail should show no recorded results
    And the stage timeline should mark a failed stage with "http_error"

  @stub
  Scenario: Operation filter requests the filtered trace list
    When I choose the "Fetch" activity filter
    Then the backend should have received a trace list request filtered by "fetch"

  @stub
  Scenario: Keyboard opens and closes trace detail with focus return
    When I focus the first "View details" control and press Enter
    Then the trace detail dialog should be visible
    When I press Escape
    Then the trace detail dialog should close and focus should return to "View details"
