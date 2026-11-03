@project-api-keys @stub
Feature: Project API keys
  A project member holding tokens.manage issues, lists, rotates and revokes the
  project's API keys. The raw key appears once, in a dialog, and never reaches
  browser storage, the URL or the page after the dialog closes. Without
  tokens.manage the screen does not exist for the member. All traffic is served
  by the in-memory project stub; every stub key is plainly fake.

  Background:
    Given the projects backend is stubbed

  Scenario: Issuing a key with no expiration reveals it once and lists it
    Given I am a member of project Alpha with role project_admin
    When I open the workspace page "/p/aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa/api-keys"
    Then I see the heading "API keys"
    When I issue an API key labelled "Deploy bot" with "No expiration"
    Then the issue request asked for no expiration
    And the new API key is revealed once with the shown-only-once warning
    And the revealed API key is in neither browser storage nor the URL
    When I close the API key reveal dialog
    Then the revealed API key is gone from the page
    And the revealed API key is in neither browser storage nor the URL
    And the API key row "Deploy bot" shows "No expiration"
    And the API key row "Deploy bot" shows "Never"
    And the API key row "Deploy bot" shows "member@example.com"
    And the API key row "Deploy bot" shows "Active"

  Scenario: Rotating a key with the default 24 hour overlap reveals the new key once
    Given I am a member of project Alpha with role project_admin
    And project Alpha has an API key labelled "CI runner"
    When I open the workspace page "/p/aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa/api-keys"
    And I rotate the API key "CI runner" with the default options
    Then the rotate request kept the 24 hour overlap and the current lifetime
    And the new API key is revealed once with the shown-only-once warning
    When I close the API key reveal dialog
    Then the revealed API key is gone from the page
    And the revealed API key is in neither browser storage nor the URL
    And the API keys table lists 2 rows labelled "CI runner"

  Scenario: Revoking a key after confirmation lists it as revoked without actions
    Given I am a member of project Alpha with role project_admin
    And project Alpha has an API key labelled "Nightly batch"
    When I open the workspace page "/p/aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa/api-keys"
    And I revoke the API key "Nightly batch" and confirm
    Then the API key row "Nightly batch" shows "Revoked"
    And the API key row "Nightly batch" offers no Rotate or Revoke action

  Scenario: A member without tokens.manage has no API keys screen
    Given I am a member of project Alpha with role project_member
    When I open the workspace page "/p/aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
    Then the Project navigation lists exactly "Overview, Playground, Activity, Usage, Providers, Settings, Members"
    When I open the workspace page "/p/aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa/api-keys"
    Then the page URL path should be "/p/aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
    And I see the heading "Alpha"
    And the heading "API keys" is absent
    And the API key issue form is absent

  Scenario: Two tabs on different projects keep separate API key drafts, keys and access
    Given I am a member of project Alpha with role project_admin
    And I am a member of project Beta with role project_admin
    And project Alpha has an API key labelled "Alpha runner"
    When I open the workspace page "/p/aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa/api-keys"
    And I open a second tab on the workspace page "/p/bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb/api-keys"
    And I type "Beta deploy" into the API key label of the second tab
    Then the first tab's API key label is empty
    When I issue the drafted API key with "No expiration" in the second tab
    And I focus both tabs again
    Then the first tab lists the API key "Alpha runner"
    And the first tab does not list the API key "Beta deploy"
    And the second tab lists the API key "Beta deploy"
    And the second tab does not list the API key "Alpha runner"
    When the project role in Alpha is revoked
    And I focus both tabs again
    Then the first tab has no API keys screen
    And the second tab still offers the API key issue form
