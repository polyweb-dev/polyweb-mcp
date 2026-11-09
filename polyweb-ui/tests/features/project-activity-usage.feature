@project-activity @stub
Feature: Project activity and usage
  Activity and Usage are sections of one project (TASK-000047 U2). Activity
  lists the project's traces newest first with Operation and Outcome filters
  held in the URL query and cursor pages behind "Load more"; closing a trace
  detail keeps the filters and every loaded row. The detail explains a
  payload the project's trace policy did not store, and a trace the project
  can no longer read. Usage shows this project's totals only and links to
  Activity for single calls. The default stubbed session is a project member
  of Alpha.

  Background:
    Given the stubbed session works in project Alpha

  Scenario: Outcome filter, Load more and a closed detail keep the loaded list
    Given project Alpha holds 60 older failed fetch traces
    When I open the "activity" section of project Alpha
    Then I should see the "Activity" heading
    When I set the Activity "Outcome" filter to "Error"
    Then the Activity URL query should be "outcome=error"
    And the backend should have received a project trace list request with "outcome=error"
    And the Activity list should show 50 traces
    And every listed trace should have the outcome "Error"
    And the Activity list should offer "Load more"
    When I load more traces
    Then the Activity list should show 61 traces
    And the backend should have received a project trace list request with "outcome=error&cursor=*"
    And the Activity list should not offer "Load more"
    When I open the "View details" control in row 55
    Then the trace detail dialog should be visible
    When I close the trace detail dialog
    Then the Activity URL query should be "outcome=error"
    And the Activity "Outcome" filter should show "Error"
    And the Activity list should show 61 traces
    And every listed trace should have the outcome "Error"
    And the removed global trace read should not have been called

  Scenario: Trace detail explains stored-metadata, missing results and unreadable traces
    Given project Alpha recorded a metadata-only, a results-not-stored and a pruned trace
    When I open the "activity" section of project Alpha
    And I open the detail of the metadata-only trace
    Then the trace detail should say "Metadata only"
    And the trace detail opens in Summary
    When I close the trace detail dialog
    And I open the detail of the results-not-stored trace
    Then the trace detail should say "The results of this trace were not stored."
    And the trace detail should say "results not stored probe"
    And the trace detail should not say "Metadata only"
    When I close the trace detail dialog
    And I open the detail of the pruned trace
    Then the trace detail should say "This trace is not available in this project."

  Scenario: Usage shows this project's totals only and links to Activity
    Given the stubbed session works in project Beta
    When I open the "usage" section of project Alpha
    Then I see the heading "Usage"
    And I see "What this project's calls used, per provider"
    And the "Usage totals" table should have the columns "Provider, Operation, Calls, Reported cost (USD), Billed requests, Other units"
    And the "Usage totals" table should show a "brave" "search" row
    And the "Usage totals" table should show "14" in the "brave" row
    And the "Usage totals" table should show a "keenable" "fetch" row
    And the "Usage totals" table should show "Not reported" in the "brave" row
    And I see "Known cost"
    And I see "See every call in Activity"
    And no usage table should show the usage of project Beta
    When I open the "usage" section of project Beta
    Then the "Usage totals" table should show "777" in the "exa" row
    And the "Usage totals" table should not show a "brave" row
