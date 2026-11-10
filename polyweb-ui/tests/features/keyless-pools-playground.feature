@task-000065 @keyless-pools
Feature: New-project keyless pools, playground errors, trace storage and results input
  # TASK-000065 regression coverage. Verified on-disk UI contracts used below:
  # - No-pool guidance: "No provider is set up for this project." plus the
  #   "Set up providers" link (ProviderSetupNotice; SearchSection/FetchSection
  #   map backend "no provider is configured for this project" to it).
  # - Playground search: "Search the web" placeholder, "Search" submit,
  #   "Number of results" spinbutton; live results carry "% match" text.
  # - Keys and pools: "Keys and pools" heading, "Add key"/"Create pool"
  #   dialogs, pool row menu with "Edit pool", "Copy to another project",
  #   "Remove from project"/"Assign to project", "Delete pool".
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
    When I submit the playground search query "fresh project no-pool probe"
    Then the playground should show the no-pool setup guidance with a link to set up providers
    And the playground should show no search results
    And the no-pool error should not present as a timeout

  @live
  Scenario: Fresh project with a keyless pool runs Playground and stores Full trace results
    Given a fresh signup with a new project
    When I create a keyless pool for Keenable without an API key and assign it to the new project
    And I follow the "Playground" link of the Project navigation
    And I submit the playground search query "fresh project keyless probe"
    Then the playground should show live search results without an API-failure alert
    When I follow the "Activity" link of the Project navigation
    And I open the Full trace detail of the successful search
    Then the trace detail should show the recorded results

  @stub
  Scenario: Bulk pool creation across providers without provider calls
    Given the projects backend is stubbed for a system administrator
    And I am a member of project Alpha with role project_admin
    When I bulk create pools for "Brave Search, Tavily, Keenable" for project Alpha without provider calls
    Then project Alpha should have pools for "Brave Search, Tavily, Keenable"
    And no vendor request should have been made

  @stub
  Scenario: Keyless free-tier defaults without API keys and without provider calls
    Given the projects backend is stubbed for a system administrator
    And I am a member of project Alpha with role project_admin
    When I create the keyless free-tier default pools for project Alpha without an API key
    Then project Alpha should have a keyless pool for Keenable without an API key
    And no vendor request should have been made

  @stub
  Scenario: Pool popup and menu actions expose consistent icons
    Given the projects backend is stubbed for a system administrator
    And I am a member of project Alpha with role project_admin
    And I add a Brave Search vault key labelled "Alpha Brave" with a fake secret
    And I create a Search pool "Alpha Search" for project Alpha on key "Alpha Brave"
    When I open the pool actions menu for "Alpha Search"
    Then the pool actions menu should show Edit pool, Copy to another project, Remove from project and Delete pool each with an icon
