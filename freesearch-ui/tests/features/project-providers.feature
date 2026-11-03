@project-providers @stub
Feature: Project providers
  A project's Providers page shows, per provider type, the system state, the
  credentials the project may bind (its own private keys and granted system
  credentials), its bindings with per-operation toggles and the effective
  operations, plus this project's shared-pool allocations. A new binding starts
  turned off. Private keys are write-only: the secret travels once, in the
  create or rotate request body, and never reaches the page, browser storage,
  the URL or the console. All traffic is served by the in-memory stub and every
  secret is plainly fake.

  Background:
    Given the projects backend is stubbed
    And the provider configuration is stubbed

  Scenario: Provider types show system state, credentials, effective operations and allocations
    Given I am a member of project Alpha with role project_admin
    When I open the Providers page of project Alpha
    Then I see the heading "Providers"
    And the "Brave Search" provider shows "Runs: search"
    And the "Tavily" provider shows "Runs: nothing yet"
    And the "Exa" provider shows "Disabled by system"
    And the "Tavily" credentials table lists "Shared Tavily" with "System (granted)" and "API key"
    And the "Tavily" credentials table lists "Alpha Tavily key" with "Project" and "API key"
    And the capacity allocations read:
      | badge         | text                                                                                                                                                  |
      | Loans enabled | Guaranteed 5 per second under contention (weight 2). Can borrow up to 10 per second when the pool is idle. The pool limit always applies. |
      | Strict cap    | Up to 60 per minute. Unused capacity of other projects is not lent.                                                                                   |
    And I see "Set by a system administrator."

  Scenario: A new binding starts turned off and enabling search updates the effective operations
    Given I am a member of project Alpha with role project_admin
    When I open the Providers page of project Alpha
    And I add a "Tavily" binding to "Shared Tavily" with route label "tavily-main"
    Then the binding create request carried no enabled operations
    And I see "New bindings start turned off. Turn on search or fetch to use it."
    And the search toggle of binding "tavily-main" is off
    And the fetch toggle of binding "tavily-main" is off
    And the "Tavily" provider shows "Runs: nothing yet"
    When I turn on search for binding "tavily-main"
    Then the last binding update enabled exactly "search"
    And the search toggle of binding "tavily-main" is on
    And the "Tavily" provider shows "Runs: search"
    When I remove the binding "brave-primary"
    Then the binding "brave-primary" is removed
    And the "Brave Search" provider shows "Runs: nothing yet"

  Scenario: Saving a private key sends the secret once and keeps it out of the browser
    Given I am a member of project Alpha with role project_admin
    When I open the Providers page of project Alpha
    And I add a provider key for "Tavily" labelled "Alpha Tavily backup" with API key "fake-provider-key-123"
    Then I see "Key saved for Alpha Tavily backup."
    And the secret "fake-provider-key-123" was sent only in the credential create request
    And the secret "fake-provider-key-123" is nowhere in the page, browser storage, URL or console
    And no secret input holds a value
    And the providers page offers no way to reveal or copy a key
    And the "Tavily" credentials table lists "Alpha Tavily backup" with "Project" and "API key"

  Scenario: Rotating a key that changed elsewhere explains the conflict, then deleting it removes it
    Given I am a member of project Alpha with role project_admin
    When I open the Providers page of project Alpha
    And someone else rotates the key "Alpha Tavily key"
    And I rotate the key "Alpha Tavily key" with "fake-provider-key-456"
    Then the last rotate request expected generation 1
    And I see "This key changed since you opened it. Reload and try again."
    And the secret "fake-provider-key-456" is nowhere in the page, browser storage, URL or console
    When I close the open dialog
    And I delete the key "Alpha Tavily key" and confirm
    Then the "Tavily" credentials table does not list "Alpha Tavily key"
    And the stub no longer holds the credential "Alpha Tavily key"

  Scenario: A project member sees providers read-only with a best-effort allocation
    Given I am a member of project Beta with role project_member
    When I open the Providers page of project Beta
    Then I see the heading "Providers"
    And I see "You can view providers. Ask a project administrator to change them."
    And the providers page offers no configuration controls
    And the search toggle of binding "beta-brave" is disabled
    And the capacity allocations read:
      | badge       | text                                                          |
      | Best effort | No guaranteed share. Runs only when the pool has idle capacity. |
    And I see "Set by a system administrator."
