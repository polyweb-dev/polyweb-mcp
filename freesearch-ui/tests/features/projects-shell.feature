Feature: Project shell and membership UX
  The desktop shell gains a project selector, project-scoped URLs, and
  membership administration driven by live backend permissions. Drafts and
  access state are isolated per (account, project) and per tab. Accounts carry
  no role: system permissions come from GET /api/v1/system/access and project
  permissions from GET /api/v1/projects/{id}/access.

  Background:
    Given the projects backend is stubbed

  @stub
  Scenario: An account without memberships sees the empty state
    Given I hold no project memberships
    When I open the workspace page "/projects"
    Then I see "You are not a member of any project."
    And I see "Ask a system administrator to add you."
    And the create project form is absent
    When I open the workspace page "/p/aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
    Then I see "Project unavailable"

  @stub
  Scenario: A deep link into Beta members renders after session restore
    Given I am a member of project Beta with role project_member
    When I open the workspace page "/p/bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb/members"
    Then the members table shows "member@example.com"

  @stub
  Scenario: A rapid project switch drops the late Alpha members response
    Given I am a member of project Alpha with role project_admin
    And I am a member of project Beta with role project_admin
    And the members response for Alpha is delayed
    When I open the workspace page "/p/aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa/members"
    And I select project Beta from the project selector
    And the delayed Alpha members request has settled
    Then the members table shows "member@example.com"
    And the members table does not show "alpha-peer@example.com"

  @stub
  Scenario: Two tabs keep separate drafts and live access per project
    Given I am a member of project Alpha with role project_admin
    And I am a member of project Beta with role project_admin
    When I open the workspace page "/p/aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa/members"
    And I open a second tab on the workspace page "/p/bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb/members"
    Then the second tab shows the members table of Beta
    And the first tab has member management controls
    When I type "teammate@example.com" into the field "Account email" of the second tab
    Then the first tab's draft field is empty
    And the project role in Alpha is revoked
    When I focus both tabs again
    Then the first tab has no member management controls
    And the second tab still has member management controls
    And the second tab's draft still contains "teammate@example.com"

  @stub
  Scenario: A system administrator creates a project and lands on its overview
    Given the projects backend is stubbed for a system administrator
    When I open the workspace page "/projects"
    And I fill "Project name" with "Gamma"
    When I submit the create project form
    Then I see the heading "Gamma"
    And the page URL path should be "/p/cccccccc-3333-4333-8333-cccccccccccc"
    When I open the workspace page "/p/cccccccc-3333-4333-8333-cccccccccccc/usage"
    Then the page URL path should be "/p/cccccccc-3333-4333-8333-cccccccccccc"
    And the heading "Usage" is absent

  @stub
  Scenario: Only project.create offers the create project form
    Given the projects backend is stubbed with system permissions "system.projects.create, system.settings.read"
    And I am a member of project Alpha with role project_member
    When I open the workspace page "/projects"
    Then I see the heading "Projects"
    And I see "Alpha"
    And the create project form is absent

  @stub
  Scenario: The root path reopens the last explicitly selected project
    Given I am a member of project Alpha with role project_member
    And I am a member of project Beta with role project_member
    When I open the workspace page "/projects"
    And I select project Beta from the project selector
    Then the page URL path should be "/p/bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
    When I open the workspace page "/"
    Then the page URL path should be "/p/bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
    And I see the heading "Beta"

  @stub
  Scenario Outline: The selected project and active screen stay visible at <width> by <height>
    Given I am a member of project Alpha with role project_admin
    When I open the workspace page "/p/aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa/api-keys" at <width> by <height>
    Then the project selector names "Alpha" within the viewport
    And the active Project link "API keys" is current within the viewport
    And the heading "API keys" is within the viewport

    Examples:
      | width | height |
      | 1280  | 800    |
      | 1440  | 900    |
