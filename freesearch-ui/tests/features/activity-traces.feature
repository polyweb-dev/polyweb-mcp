Feature: Activity trace redesign acceptance
  The Activity list stays scannable and payload-free; a seven-provider fanout
  trace discloses one nested row per provider attempt with span-recorded
  identities; Inspect opens a provider-scoped dialog; the detail explains
  ranking once in mode-appropriate words; results select into a side
  inspector; a Trajectory view fuses timing into hierarchical rows with a
  side span inspector; the dialog holds its geometry and focus contract at
  desktop and narrow widths.

  Background:
    Given I navigate to the web application
    When I select the "Activity" header tab
    Then I should see the "Activity" heading

  @stub
  Scenario: Trace list shows Actions with real buttons and no payloads
    Then the activity table should expose the columns "Time", "Operation", "Provider", "Status", "Latency", and "Results" with a "Actions" action column
    And the activity list should not contain the disclosed query or result URLs
    And each activity row should expose a "View details" button
    And every "View details" control should be a real button

  @stub
  Scenario: Seven-provider fanout expands to seven span-recorded identities
    When I expand the all-providers trace
    Then the nested provider rows should show "Brave" with "412ms" and "1" results
    And the nested provider rows should show "Keenable" with "2025ms" and "1" results
    And the nested provider rows should show "Tavily" with "3223ms" and "1" results
    And the nested provider rows should show "Exa" with "618ms" and "1" results
    And the nested provider rows should show "Firecrawl" with "940ms" and "1" results
    And the nested provider rows should show "Youcom" with "755ms" and "1" results
    And the nested provider rows should show "Parallel" with "410ms" and "—" results
    And the seven-provider trace should show no anonymous provider text
    And each nested provider row should expose an "Inspect" button
    When I collapse the all-providers trace
    Then no nested provider row should be visible

  @stub
  Scenario: Modal and summary-strip geometry hold at desktop width
    Given I use a desktop viewport
    When I open the "View details" control in row 1
    Then the trace detail dialog should be visible
    And the trace detail dialog width should be approximately "1200" pixels within "64" pixels
    And the dialog should stay within the viewport
    And the summary strip cells should share equal top and height
    And the summary strip cells should have at least "15" pixels of horizontal inner padding
    And the summary strip, query, and inspection workspace should align within "2" pixels
    And the trace detail dialog should have no horizontal overflow
    And the document should have no horizontal overflow
    And the dialog header should stay visible after scrolling the body

  @stub
  Scenario: Parent detail explains the fusion order exactly once
    When I open the "View details" control in row 1
    Then the trace detail dialog should be visible
    And the trace detail should explain "Results are shown in FreeSearch's final fused order. Higher recorded fusion scores appear first." exactly once
    And the trace detail should explain "Raw reciprocal-rank inputs and per-provider ranks are not recorded, so exact RRF arithmetic is unavailable." exactly once
    And the trace detail should not contain the legacy ranking copy
    And the trace detail should not repeat a missing-contributor note
    And the trace detail should not show a duplicate ranked list

  @stub
  Scenario: Provider scope explains the provider order exactly once
    When I expand the all-providers trace
    And I inspect the "Keenable" provider response
    Then the trace detail dialog should be visible
    And the provider-scoped dialog should show "Keenable response"
    And the provider-scoped dialog should show the scope note
    And the trace detail should explain "Results keep the order returned by Keenable. Recorded provider scores are shown as metadata; FreeSearch did not reorder this response." exactly once
    And the trace detail should not contain the legacy ranking copy
    And the trace detail should not repeat a missing-contributor note
    And the backend should have received a cached detail reuse

  @stub
  Scenario: Selecting a result shows its full payload in the side inspector
    When I open the "View details" control in row 1
    Then the trace detail dialog should be visible
    And the compact result rows should not contain the seeded long snippet
    When I select the result "Keenable acceptance result"
    Then the result "Keenable acceptance result" should be marked as selected
    And the result inspector should show the full "Keenable" payload
    When I select the result "Brave acceptance result"
    Then the result "Brave acceptance result" should be marked as selected
    And the result inspector should show the full "Brave" payload without growing the page

  @stub
  Scenario: Trajectory fuses timing into rows with a side span inspector
    When I open the "View details" control in row 1
    Then the trace detail dialog should be visible
    When I switch to the "Trajectory" trace view
    Then the trajectory should show seven provider rows each with a duration and a latency bar
    And the trace detail should not show a separate "Latency" section
    And the trace detail should not show a "Technical trajectory" disclosure
    When I select the trajectory row "Keenable request"
    Then the span inspector should show provider "Keenable" with the recorded request and response payload

  @stub
  Scenario: Dialog takes focus on open and traps Tab until Escape
    Given I use a desktop viewport
    When I focus the first "View details" control and press Enter
    Then the trace detail dialog should be visible
    And the dialog should take focus on open
    When I press Tab
    Then focus should stay inside the dialog
    When I press Escape
    Then the trace detail dialog should close and focus should return to "View details"

  @stub
  Scenario: Result and trajectory rows select with the keyboard
    When I open the "View details" control in row 1
    Then the trace detail dialog should be visible
    When I focus the result "Keenable acceptance result" and press Enter
    Then the result "Keenable acceptance result" should be marked as selected
    And the result inspector should show the full "Keenable" payload
    When I switch to the "Trajectory" trace view
    And I focus the trajectory row "Keenable request" and press Enter
    Then the span inspector should show provider "Keenable" with the recorded request and response payload
    When I press Escape
    Then the trace detail dialog should close and focus should return to "View details"

  @stub
  Scenario: Single-provider detail keeps provider order and recorded metadata
    When I open the single-provider trace detail
    Then the trace detail dialog should be visible
    And the trace detail summary should show status "success" and provider "Keenable"
    And the trace detail should show the query "distributed consensus algorithms"
    And the trace detail should mention result "https://docs.freesearch.dev/consensus" with title "Consensus algorithms explained"
    And the trace detail should explain "Results keep the order returned by Keenable. Recorded provider scores are shown as metadata; FreeSearch did not reorder this response." exactly once
    And the trace detail should not repeat a missing-contributor note

  @stub
  Scenario: Error fetch detail shows the failure and the failed stage
    When I open the error trace detail
    Then the trace detail dialog should be visible
    And the trace detail should show an error "http_error: HTTP 502"
    And the trace detail should show the fetched url "https://docs.freesearch.dev/getting-started"
    And the trace detail should show no recorded results

  @stub
  Scenario: Operation filter requests the filtered trace list
    When I choose the "Fetch" activity filter
    Then the backend should have received a trace list request filtered by "fetch"

  @stub
  Scenario: Trace list failure shows an error and recovers on retry
    When I inject a trace list failure "stubbed list outage"
    And I refresh the activity list
    Then the activity list should show error "stubbed list outage" with a retry
    When I clear the trace list failure and retry
    Then the activity table should expose the columns "Time", "Operation", "Provider", "Status", "Latency", and "Results" with a "Actions" action column

  @stub
  Scenario: Trace detail failure shows an error and recovers on retry
    When I inject a trace detail failure "stubbed detail outage"
    And I open the "View details" control in row 1
    Then the trace detail should show error "stubbed detail outage" with a retry
    When I clear the trace detail failure and retry
    Then the trace detail dialog should be visible
    And the trace detail should show the query "seven-provider fanout acceptance probe"

  @stub
  Scenario: Nested provider panel failure shows an error and recovers on retry
    When I inject a trace detail failure "stubbed nested outage"
    And I expand the all-providers trace
    Then the nested provider panel should show error "stubbed nested outage" with a retry
    When I clear the trace detail failure and retry the nested panel
    Then the nested provider rows should show "Keenable" with "2025ms" and "1" results

  @stub
  Scenario: Narrow viewport keeps the dialog in bounds without horizontal scroll
    Given I use a narrow viewport
    When I select the "Activity" header tab
    And I open the "View details" control in row 1
    Then the trace detail dialog should be visible
    And the dialog should stay within the viewport
    And the trace detail dialog should have no horizontal overflow
    And the document should have no horizontal overflow
    When I press Escape
    Then the trace detail dialog should close and focus should return to "View details"
