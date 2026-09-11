@stub @oauth
Feature: Parallel OAuth device pairing stays honest
  The Parallel quota row offers device-flow pairing while no vendor budget
  is configured. A pending code polls the stubbed status endpoint; ready
  auto-closes and the authoritative remaining-only USD balance takes over
  the row. Denied, expired, and failed requests keep the dialog open with
  an error and a retry. Disconnecting revokes the pairing and restores the
  unbudgeted explainer.

  Background:
    Given I navigate to the web application
    And the stubbed dashboard shows "Parallel unseeded quota"
    And the stubbed OAuth flow for "parallel" is unpaired

  @stub @oauth @ready
  Scenario: Pairing completes and the authoritative balance takes over
    When I navigate directly to "/usage"
    And I start OAuth pairing for provider "parallel"
    Then the OAuth pairing dialog should show the user code
    And the OAuth pairing dialog should link to the verification URL
    When the stubbed backend pairs "parallel" with balance "3.75"
    Then the OAuth pairing dialog should close automatically
    And the usage view should show "authoritative"
    And the usage view should show "3.75"
    And the usage view should not show "Budget not configured"

  @stub @oauth @denied
  Scenario: Denied pairing stays open and offers a retry
    When I navigate directly to "/usage"
    And I start OAuth pairing for provider "parallel"
    And the stubbed OAuth flow for "parallel" becomes "denied"
    Then the OAuth pairing should show an error
    And I should be able to retry OAuth pairing
    When I retry OAuth pairing
    And the stubbed OAuth flow for "parallel" becomes "ready"
    Then the OAuth pairing dialog should close automatically

  @stub @oauth @expired
  Scenario: Expired code offers a retry that re-begins the flow
    When I navigate directly to "/usage"
    And I start OAuth pairing for provider "parallel"
    And the stubbed OAuth flow for "parallel" becomes "expired"
    Then the OAuth pairing should show an error
    And I should be able to retry OAuth pairing
    When I retry OAuth pairing
    Then the OAuth pairing dialog should show the user code

  @stub @oauth @error
  Scenario: Failed device-code request surfaces an alert without polling
    Given the stubbed OAuth device-code request for "parallel" fails
    When I navigate directly to "/usage"
    And I attempt OAuth pairing for provider "parallel" with a failing begin
    Then the OAuth pairing should show an error
    And I should be able to retry OAuth pairing

  @stub @oauth @revoke
  Scenario: Disconnecting restores the unbudgeted explainer
    Given the stubbed dashboard shows "Parallel paired quota"
    And the stubbed OAuth flow for "parallel" is "ready"
    When I navigate directly to "/usage"
    And I disconnect OAuth pairing for provider "parallel"
    Then the usage view should show "Budget not configured"
    And the usage view should show "No API-key balance endpoint is available. Configure a local monthly USD budget to calculate remaining capacity."
