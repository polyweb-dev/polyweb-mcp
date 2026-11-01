Feature: Activity trace redesign acceptance
  The Activity list stays scannable and payload-free; a seven-provider fanout
  trace discloses one nested row per provider attempt with span-recorded
  identities; View details opens a provider-scoped dialog; the detail explains
  ranking once in mode-appropriate words; results select into a side
  inspector; the "Trace" view (formerly Trajectory) fuses timing into rows with a
  side span inspector; the dialog holds its geometry and focus contract at
  desktop and narrow widths. Activity is a project section (U2): the list
  and every detail come from the Alpha project trace routes.

  Background:
    Given the stubbed session works in project Alpha
    When I open the "activity" section of project Alpha
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
    And the nested provider rows should show "You.com" with "755ms" and "1" results
    And the nested provider rows should show "Parallel" with "410ms" and "—" results
    And the seven-provider trace should show no anonymous provider text
    And each nested provider row should expose a "View details" button
    When I collapse the all-providers trace
    Then no nested provider row should be visible

  @stub
  Scenario: Parent and provider actions share the View details label
    When I expand the all-providers trace
    Then each activity row should expose a "View details" button
    And each nested provider row should expose a "View details" button
    When I inspect the "Keenable" provider response
    Then the trace detail dialog should be visible
    And the provider-scoped dialog should show "Keenable response"
    And the provider-scoped dialog should show the scope note

  @stub
  Scenario: Provider identities show logo followed by name
    When I expand the all-providers trace
    Then the nested provider rows should show provider logos followed by names
    When I open the "View details" control in row 1
    And I select the result "Keenable acceptance result"
    Then the result inspector badges should number 1 and each show a logo
    When I switch to the "Trace" trace view
    Then the trajectory provider rows should show provider logos followed by names

  @stub
  Scenario: Modal and summary-strip geometry hold at desktop width
    Given I use a desktop viewport
    When I open the "View details" control in row 1
    Then the trace detail dialog should be visible
    And the trace detail dialog width should be approximately "1200" pixels within "64" pixels
    And the dialog should stay within the viewport
    And the summary strip cells should share equal top and height
    And the query and summary strip should share one row aligned to the inspection workspace within "2" pixels
    And the trace detail dialog should have no horizontal overflow
    And the document should have no horizontal overflow
    And the dialog header should stay visible after scrolling the body
    And the summary strip cells should have at least "15" pixels of horizontal inner padding

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
    And the compact result rows should clamp the seeded long snippet to two lines
    When I select the result "Keenable acceptance result"
    Then the result "Keenable acceptance result" should be marked as selected
    And the result inspector should show the full "Keenable" payload
    When I select the result "Brave acceptance result"
    Then the result "Brave acceptance result" should be marked as selected
    And the result inspector should show the full "Brave" payload without growing the page

  @stub
  Scenario: Fusion inspector shows recorded metadata before the long summary
    When I open the "View details" control in row 1
    Then the trace detail dialog should be visible
    When I select the result "Keenable acceptance result"
    Then the result inspector should show "Result 2 of 6" before the snippet summary
    And the result inspector should show contributor "Keenable"
    And the result inspector should show "Fusion score"

  @stub
  Scenario: Single-provider inspector shows recorded metadata before the long summary
    When I open the "View details" control in row 5
    Then the trace detail dialog should be visible
    When I select the result "Exa null-source acceptance result"
    Then the result inspector should show "Result 1 of 1" before the snippet summary
    And the result inspector should show contributor "Exa"
    And the result inspector should show "Provider score"

  @stub
  Scenario: Recorded metadata stays visible without scrolling the summary
    Given I use a desktop viewport
    When I open the "View details" control in row 6
    Then the trace detail dialog should be visible
    When I select the result "Fusion multi-engine acceptance result"
    Then the result inspector metadata should stay visible without scrolling the snippet region

  @stub
  Scenario: Full snippet stays available in its own scroll region
    When I open the "View details" control in row 6
    Then the trace detail dialog should be visible
    When I select the result "Fusion multi-engine acceptance result"
    Then the result inspector snippet should contain the full "fusion long" text in its own scroll region

  @stub
  Scenario: Fusion contributor badges match the selected result
    When I open the "View details" control in row 6
    Then the trace detail dialog should be visible
    When I select the result "Fusion multi-engine acceptance result"
    Then the result inspector should show contributor "Brave Search"
    And the result inspector should show contributor "Keenable"
    And the result inspector should not show contributor "Tavily"
    And the result inspector badges should number 2 and each show a logo
    When I select the result "Fusion single-engine acceptance result"
    Then the result inspector should show contributor "Tavily"
    And the result inspector should not show contributor "Brave Search"
    And the result inspector badges should number 1 and each show a logo

  @stub
  Scenario: Source-null Exa result keeps Exa attribution without a source warning
    When I open the "View details" control in row 5
    Then the trace detail dialog should be visible
    When I select the result "Exa null-source acceptance result"
    Then the result inspector should show contributor "Exa"
    And the result inspector should show "Not recorded"
    And the trace detail should not contain "Source not recorded"

  @stub
  Scenario: Trajectory fuses timing into rows with a side span inspector
    When I open the "View details" control in row 1
    Then the trace detail dialog should be visible
    When I switch to the "Trace" trace view
    Then the trajectory should show seven provider rows each with a duration and a latency bar
    And the trajectory should show a "Search request" row
    And the trajectory should show a "Backend handling" row
    And the trajectory should show a "Results assembly" row
    And the trajectory should show a "Response to caller" row
    And the trace detail should not show a separate "Latency" section
    And the trace detail should not show a "Technical trajectory" disclosure
    When I select the trajectory row "Keenable request"
    Then the span inspector should show provider "Keenable" with the recorded request and response payload

  @stub
  Scenario: Trajectory hides transport, parse, and function-level spans
    When I open the "View details" control in row 6
    Then the trace detail dialog should be visible
    When I switch to the "Trace" trace view
    Then the trajectory should show a "Search request" row
    And the trajectory should show a "Route selection" row
    And the trajectory should show a "Backend handling" row
    And the trajectory should show a "Brave Search request" row
    And the trajectory should show a "Results assembly" row
    And the trajectory should show a "Response to caller" row
    And the trajectory should not show a "Provider HTTP call" row
    And the trajectory should not show a "Provider response parse" row
    And the trajectory should not show a "Rank fusion" row

  @stub
  Scenario: Trajectory ruler and bars share one time axis
    When I open the "View details" control in row 1
    Then the trace detail dialog should be visible
    When I switch to the "Trace" trace view
    Then the trajectory ruler and every row track should align within "2" pixels
    And the trajectory bars should match recorded offsets and durations within "2" pixels
    And the trajectory ruler should state its millisecond unit once
    And the trajectory row should show an inset focus ring at both edges after Tab

  @stub
  Scenario: Latency summary counts overlapping provider calls once
    When I open the "View details" control in row 1
    Then the trace detail dialog should be visible
    When I switch to the "Trace" trace view
    Then the latency summary should count overlapping provider calls once

  @stub
  Scenario: Trajectory row selection replaces request and response payloads
    When I open the "View details" control in row 6
    Then the trace detail dialog should be visible
    When I switch to the "Trace" trace view
    And I select the trajectory row "Brave Search request"
    Then the span inspector should show "https://e2e.freesearch.dev/fusion/brave"
    When I select the trajectory row "Keenable request"
    Then the span inspector should show "https://e2e.freesearch.dev/fusion/keenable"
    And the span inspector should not show "https://e2e.freesearch.dev/fusion/brave"

  @stub
  Scenario: Fetch trajectory keeps the fetch total row
    When I open the error trace detail
    Then the trace detail dialog should be visible
    When I switch to the "Trace" trace view
    Then the trajectory should show a "Fetch request" row
    And the trajectory should show a "Keenable request" row

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
    When I switch to the "Trace" trace view
    And I focus the trajectory row "Keenable request" and press Enter
    Then the span inspector should show provider "Keenable" with the recorded request and response payload
    When I press Escape
    Then the trace detail dialog should close and focus should return to "View details"

  @stub
  Scenario: Narrow viewport keeps keyboard selection and focus return
    Given I use a narrow viewport
    When I open the "activity" section of project Alpha
    And I open the "View details" control in row 1
    Then the trace detail dialog should be visible
    When I focus the result "Keenable acceptance result" and press Enter
    Then the result "Keenable acceptance result" should be marked as selected
    And the result inspector should show the full "Keenable" payload
    When I press Escape
    Then the trace detail dialog should close and focus should return to "View details"
    And the document should have no horizontal overflow

  @stub
  Scenario: Single-provider detail keeps provider order and recorded metadata
    When I open the single-provider trace detail
    Then the trace detail dialog should be visible
    And the trace detail summary should show status "Success" and provider "Keenable"
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
    When I set the Activity "Operation" filter to "Fetch"
    Then the backend should have received a trace list request filtered by "fetch"
    And the Activity URL query should be "operation=fetch"
    And the removed global trace read should not have been called

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
    When I open the "activity" section of project Alpha
    And I open the "View details" control in row 1
    Then the trace detail dialog should be visible
    And the dialog should stay within the viewport
    And the trace detail dialog should have no horizontal overflow
    And the document should have no horizontal overflow
    When I press Escape
    Then the trace detail dialog should close and focus should return to "View details"
