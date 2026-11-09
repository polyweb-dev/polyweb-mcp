Feature: Project discovery freshness
  Membership changes made elsewhere reach the open workspace on focus: a
  grant lists the project without a page reload, and a revoke drops the open
  project to the unavailable view and off the list.

  Background:
    Given the projects backend is stubbed

  @stub
  Scenario: A granted membership appears on focus without a reload
    Given I hold no project memberships
    When I open the workspace page "/projects"
    Then I see "You are not a member of any project."
    When I am a member of project Beta with role project_member
    And the window regains focus
    Then I see "Beta"

  @stub
  Scenario: A revoked membership drops the open project from the list
    Given I am a member of project Beta with role project_member
    When I open the workspace page "/p/bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
    Then I see the heading "Beta"
    When the membership in project Beta is revoked
    And the window regains focus
    Then I see "Project unavailable"
    When I follow the "All projects" link
    Then I see the heading "Projects"
    And I do not see "Beta"
