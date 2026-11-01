@project-playground @stub
Feature: Project playground
  The playground is a section of one project (TASK-000047 U2). Every search
  and fetch names the URL project in its body and runs on the human session:
  no project API key is read, sent or stored in the browser. Drafts and
  results persist per account and project, a project switch cancels the
  in-flight request and never shows the old project's late result, and the
  former global /playground path follows the last explicitly chosen project.
  The session is a project member of the in-memory project stub.

  Background:
    Given the projects backend is stubbed
    And I am a member of project Alpha with role project_member

  Scenario: A playground search runs for the URL project on the human session
    Given project Alpha has an API key labelled "Deploy bot"
    When I open the workspace page "/p/aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa/playground"
    Then I should see the "Search Playground" heading
    When I submit the playground search query "alpha isolation probe"
    Then the playground should show the result "Alpha isolation result"
    And the last search request should name project Alpha
    And every search and fetch request should use the human session without an API key
    And the playground state should be persisted only under the project key of Alpha
    And browser storage should hold no API key

  Scenario: Switching project during a slow search drops the old project's result
    Given I am a member of project Beta with role project_member
    And searches for "alpha isolation probe" respond slowly
    When I open the workspace page "/p/aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa/playground"
    And I submit the playground search query "alpha isolation probe"
    Then the slow search should be in flight
    When I select project Beta from the project selector
    Then the page URL path should be "/p/bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb/playground"
    And the slow search request should have been cancelled
    And the playground search draft should be ""
    And the playground should show no search results
    When the slow search response arrives
    Then the playground should not show the result "Alpha isolation result"
    And the playground should show no search results
    When I submit the playground search query "beta isolation probe"
    Then the playground should show the result "Beta isolation result"
    And the playground should not show the result "Alpha isolation result"
    And the last search request should name project Beta

  Scenario: Two tabs on different projects keep separate playground drafts and results
    Given I am a member of project Beta with role project_member
    When I open the workspace page "/p/aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa/playground"
    And I open a second tab on the workspace page "/p/bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb/playground"
    And I type "beta draft query" into the playground search of the second tab
    Then the playground search draft should be ""
    And the playground search draft of the second tab should be "beta draft query"
    When I submit the playground search query "alpha isolation probe"
    And I submit the playground search query "beta isolation probe" in the second tab
    Then the playground should show the result "Alpha isolation result"
    And the second tab should show the result "Beta isolation result"
    And the persisted playground state of project Alpha should contain "alpha isolation probe"
    And the persisted playground state of project Beta should contain "beta isolation probe"
    When I reload both tabs
    Then the playground should show the result "Alpha isolation result"
    And the playground should not show the result "Beta isolation result"
    And the second tab should show the result "Beta isolation result"
    And the second tab should not show the result "Alpha isolation result"

  Scenario: The former playground path opens the last chosen project's playground
    When I open the workspace page "/projects"
    And I select project Alpha from the project selector
    Then the page URL path should be "/p/aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
    When I open the workspace page "/playground"
    Then the page URL path should be "/p/aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa/playground"
    And I should see the "Search Playground" heading
    When I open the workspace page "/activity"
    Then the page URL path should be "/p/aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa/activity"
    And I should see the "Activity" heading

  Scenario: The former playground path without a chosen project opens the projects list
    When I open the workspace page "/playground"
    Then the page URL path should be "/projects"
    And I see the heading "Projects"
