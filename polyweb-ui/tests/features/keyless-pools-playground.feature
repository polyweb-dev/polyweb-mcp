@task-000065 @keyless-pools
Feature: New-project keyless pools, playground errors, trace storage and results input
  # TASK-000065 regression coverage. Verified on-disk UI contracts used below:
  # - No-pool preflight: `noProviderForMode` renders the create/assign pool
  #   guidance with the Search submit disabled; zero /search + /fetch execution
  #   calls observed on the live page (never submits a disabled button).
  # - Playground search: "Search the web" placeholder, "Search" submit;
  #   live results carry "% match" text.
  # - Keys and pools: route /account/keys, "Keys and pools" heading, dialog
  #   "Add key" with "Add key" submit, Create pool via the key-row button.
  # - Settings: field "Payload detail", option "Full requests".
  # - Trace detail: dialog "Trace detail", results list "Ranked results".
  # - Pool menu: RowActionsMenu Popover plain buttons inside
  #   [data-slot=popover-content], one svg icon per action.
  # Live preconditions (never exercised during authoring): an authenticated
  # session with project-creation rights; "fresh" means a project created
  # inside the scenario, so it starts with zero pools. @live scenarios make
  # real backend requests only when executed, never while writing them.
  # ANTICIPATED (missing product behavior these scenarios pin down): keyless
  # key creation without a secret, one-shot bulk pool creation, keyless
  # free-tier default pools, and one icon per pool menu item.

  @live
  Scenario: Fresh project with no pool shows actionable create-or-assign guidance
    Given a fresh signup with a new project with no provider pool
    And I follow the "Playground" link of the Project navigation
    Then the playground shows the create-or-assign pool guidance for the new project
    And the playground shows no search results
    And the no-pool error should not present as a timeout

  @live
  Scenario: Fresh project with a keyless pool runs Playground and stores Full trace results
    Given a fresh signup with a new project
    When I create a keyless pool for Keenable without an API key and assign it to the new project
    And I run the keyless search and save the payload with Full requests
    Then the playground should show live search results without an API-failure alert
    When I open the trace of the saved search response
    Then the trace detail shows the Keenable response with its results

  @smoke @stub
  Scenario: Bulk pool creation across providers without provider calls
    Given the projects backend is stubbed for a system administrator
    And I am a member of project Alpha with role project_admin
    When I bulk create pools for "Brave Search, Tavily, Keenable" for project Alpha without provider calls
    Then project Alpha has new pools for "Brave Search, Tavily, Keenable" assigned to Alpha
    And no vendor request should have been made

  @smoke @stub
  Scenario: Keyless free-tier defaults without API keys and without provider calls
    Given the projects backend is stubbed for a system administrator
    And I am a member of project Alpha with role project_admin
    When I create the keyless free-tier default pools for project Alpha without an API key
    Then project Alpha has a new keyless pool for Keenable assigned to Alpha
    And no vendor request should have been made

  @smoke @stub
  Scenario: Pool popup and menu actions expose consistent icons
    Given the projects backend is stubbed for a system administrator
    And I am a member of project Alpha with role project_admin
    And I add a Brave Search vault key labelled "Alpha Brave" with a fake secret
    And I create a Search pool "Alpha Search" for project Alpha on key "Alpha Brave"
    When I open the pool actions menu for "Alpha Search"
    Then the pool actions menu should show Edit pool, Copy to another project, Remove from project and Delete pool each with an icon
