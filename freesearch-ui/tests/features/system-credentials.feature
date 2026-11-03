@system-credentials @stub
Feature: System credentials
  An account holding system.credentials.manage manages system-owned provider
  credentials on /system/credentials: create (API key or Parallel OAuth),
  rotate, delete, OAuth connect, and per-project grants limited to the
  operations the provider supports. Secrets are write-only. Without the
  permission the "System credentials" link and page do not exist. Served by
  the in-memory stub; every secret is plainly fake.

  Background:
    Given the projects backend is stubbed for a system administrator
    And the provider configuration is stubbed
    And I am a member of project Alpha with role project_admin
    And I am a member of project Beta with role project_member

  Scenario: Creating a system key sends the secret once and lists only metadata
    When I open the workspace page "/projects"
    And I follow the "System credentials" sidebar link
    Then I see the heading "System credentials"
    And the system credentials table lists "Shared Tavily" with "API key"
    And the system credentials table lists "Shared Brave" with "2"
    When I add a system credential for "Brave Search" labelled "Brave backup" with API key "fake-provider-key-123"
    Then the system credentials table lists "Brave backup" with "1"
    And the secret "fake-provider-key-123" was sent only in the credential create request
    And the secret "fake-provider-key-123" is nowhere in the page, browser storage, URL or console
    And no secret input holds a value

  Scenario: Rotating a system key sends the expected generation and the new secret once
    When I open the workspace page "/system/credentials"
    And I rotate the key "Shared Brave" with "fake-provider-key-789"
    Then the last rotate request expected generation 2
    And the system credentials table lists "Shared Brave" with "3"
    And the secret "fake-provider-key-789" was sent only in the credential rotate request
    And the secret "fake-provider-key-789" is nowhere in the page, browser storage, URL or console

  Scenario: Grants offer only supported operations and can be added and removed
    When I open the workspace page "/system/credentials"
    And I open the grants of "Shared Brave"
    Then the grants list "Alpha" with "search"
    And the grants list "Beta" with "search"
    And the grant form offers "Search" but not "Fetch"
    When I remove the grant for "Beta"
    Then "Shared Brave" has no grant for project Beta
    When I close the open dialog
    And I open the grants of "Shared Tavily"
    And I grant project "Beta" the operations "Fetch"
    Then the last grant request for project Beta permitted "fetch"
    And the grants list "Beta" with "fetch"

  Scenario: A Parallel OAuth system credential shows only the user code and reaches Connected
    When I open the workspace page "/system/credentials"
    And I add a system OAuth credential for "Parallel" labelled "Parallel shared"
    Then the last credential create request used OAuth without a secret
    When I connect the credential "Parallel shared"
    Then the OAuth dialog shows only the user code and the verification link
    And the OAuth dialog status reads "Waiting for approval…"
    When the Parallel account approves the device for "Parallel shared"
    Then the OAuth dialog status reads "Connected"
    And the OAuth user code is in neither browser storage nor the URL

  Scenario: Without system.credentials.manage there is no System credentials link or page
    Given the projects backend is stubbed with system permissions "system.settings.read"
    And the provider configuration is stubbed
    When I open the workspace page "/projects"
    Then the Primary navigation lists exactly "Routing, Provider usage, Provider settings, Projects, Account"
    When I open the workspace page "/system/credentials"
    Then the page URL path should not be "/system/credentials"
    And the heading "System credentials" is absent
