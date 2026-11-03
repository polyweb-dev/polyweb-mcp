@stub @oauth
Feature: Parallel OAuth connects one credential
  Parallel OAuth belongs to one credential instance: a project's private
  Parallel credential (or a system credential, see system-credentials.feature)
  starts the device flow from its own row. The dialog shows only the user code,
  a link to the verification page and the connection status; nothing else from
  the device response is rendered or stored. Polling follows the server
  interval and stops when the flow ends or the dialog closes. An OAuth key is
  created without a secret. Provider usage no longer offers pairing.

  Background:
    Given the projects backend is stubbed
    And the provider configuration is stubbed
    And I am a member of project Alpha with role project_admin

  @ready
  Scenario: Connecting shows only the user code and the verification link and reaches Connected
    Given project Alpha has a private Parallel OAuth credential "Alpha Parallel"
    When I open the Providers page of project Alpha
    And I connect the credential "Alpha Parallel"
    Then the OAuth dialog shows only the user code and the verification link
    And the OAuth dialog status reads "Waiting for approval…"
    When the Parallel account approves the device for "Alpha Parallel"
    Then the OAuth dialog status reads "Connected"
    And the OAuth state of "Alpha Parallel" is "connected"
    And the OAuth user code is in neither browser storage nor the URL
    And polling for "Alpha Parallel" has stopped

  @denied
  Scenario: A denied device flow ends as not connected and stops polling
    Given project Alpha has a private Parallel OAuth credential "Alpha Parallel"
    When I open the Providers page of project Alpha
    And I connect the credential "Alpha Parallel"
    And the Parallel account denies the device for "Alpha Parallel"
    Then the OAuth dialog status reads "Not connected"
    And polling for "Alpha Parallel" has stopped

  @close
  Scenario: Closing the dialog stops polling a pending flow
    Given project Alpha has a private Parallel OAuth credential "Alpha Parallel"
    When I open the Providers page of project Alpha
    And I connect the credential "Alpha Parallel"
    Then the OAuth dialog status reads "Waiting for approval…"
    And the device flow of "Alpha Parallel" is being polled
    When I close the OAuth dialog
    Then polling for "Alpha Parallel" has stopped

  @revoke
  Scenario: Disconnecting a connected credential offers Connect again
    Given project Alpha has a private Parallel OAuth credential "Alpha Parallel"
    When I open the Providers page of project Alpha
    And I connect the credential "Alpha Parallel"
    And the Parallel account approves the device for "Alpha Parallel"
    Then the OAuth dialog status reads "Connected"
    When I close the OAuth dialog
    And I disconnect the credential "Alpha Parallel"
    Then the OAuth state of "Alpha Parallel" is "disconnected"
    And the credential "Alpha Parallel" offers "Connect Alpha Parallel"

  @create
  Scenario: Creating a private Parallel OAuth key sends no secret
    When I open the Providers page of project Alpha
    And I add a private OAuth key for "Parallel" labelled "Alpha Parallel"
    Then the last credential create request used OAuth without a secret
    And I see "Key saved for Alpha Parallel."
    And the credential "Alpha Parallel" offers "Connect Alpha Parallel"
