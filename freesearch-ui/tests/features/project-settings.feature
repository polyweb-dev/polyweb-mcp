@project-settings @stub
Feature: Project settings
  A project's Settings page shows the Trace policy fields, the only settings
  calls apply today; the stored routing and execution settings stay hidden.
  With settings.write a field can be overridden or reset
  to inherit; one save sends only the changed fields with the expected
  revision, an out-of-range number shows its allowed range, and a stale
  revision asks for a reload. Copying settings from another project is a
  revision-bound preview then apply; the preview writes nothing. Served by the
  in-memory stub.

  Background:
    Given the projects backend is stubbed
    And the provider configuration is stubbed

  Scenario: Only applied fields show, with a hint only where the project overrides them
    Given I am a member of project Alpha with role project_admin
    And I am a member of project Beta with role project_admin
    When I open the Settings page of project Alpha
    Then I see the heading "Settings"
    And I see the heading "Trace policy"
    And the settings page shows no field "routing.max_attempts"
    And the settings page shows no field "execution.cache_enabled"
    And the settings field "trace.retention_days" shows "Traces older than this limit are deleted."
    And the settings field "trace.retention_days" shows "Your override exceeds the system limit; the system limit applies."
    And the settings page shows no field "trace.sampling_rate"
    And the settings page shows no field "trace.payload_redaction"
    And the settings field "trace.detail" shows "API keys, auth headers, cookies, passwords and tokens are always removed from traces."
    And the settings field "trace.detail" shows "Full requests"
    When I open the Settings page of project Beta
    Then the settings field "trace.retention_days" shows "Keep all traces."
    And trace deletion is off
    When I set the settings field "trace.detail" labelled "Payload detail" to "Metadata only"
    Then the settings field "trace.detail" shows "Metadata only"

  Scenario: One save sends only the changed fields and Reset sends null
    Given I am a member of project Alpha with role project_admin
    When I open the Settings page of project Alpha
    And I set the settings field "trace.retention_days" labelled "Days" to "60"
    And I save the settings
    Then I see "Settings saved"
    And the last settings save sent exactly:
      """
      { "expected_revision": 2, "trace": { "retention_days": 60 } }
      """
    When I turn off trace deletion
    And I save the settings
    Then the last settings save sent exactly:
      """
      { "expected_revision": 3, "trace": { "retention_days": null } }
      """
    And the settings field "trace.retention_days" shows "Keep all traces."

  Scenario: An out-of-range number shows its range and is not saved
    Given I am a member of project Alpha with role project_admin
    When I open the Settings page of project Alpha
    And I set the settings field "trace.retention_days" labelled "Days" to "400"
    Then the settings field "trace.retention_days" shows "Enter a whole number from 1 to 90"
    When I save the settings
    Then I see "Fix the highlighted fields before saving"

  Scenario: A stale save asks to reload the settings
    Given I am a member of project Alpha with role project_admin
    When I open the Settings page of project Alpha
    And project Alpha settings change elsewhere
    And I set the settings field "trace.retention_days" labelled "Days" to "60"
    And I save the settings
    Then I see "Settings changed since you opened them."
    When I reload the settings
    Then the settings were read again
    And I do not see "Settings changed since you opened them."

  Scenario: The system can limit traces to metadata
    Given the system limits traces to metadata
    And I am a member of project Alpha with role project_admin
    When I open the Settings page of project Alpha
    Then the settings field "trace.detail" shows "The system limit is metadata only."

  Scenario: A project member sees settings read-only without copy
    Given I am a member of project Alpha with role project_member
    When I open the Settings page of project Alpha
    Then I see "You can view these settings. Ask a project administrator to change them."
    And the settings field "trace.retention_days" shows "90"
    And the settings page offers no editing controls

  Scenario: Copy previews first, then applies the preview's revisions and selected bindings
    Given I am a member of project Alpha with role project_admin
    And I am a member of project Beta with role project_member
    When I open the Settings page of project Alpha
    And I open the copy settings dialog
    Then the copy dialog offers "Preview changes"
    When I choose "Beta" as the copy source
    And I preview the copy
    Then the copy preview lists "Fallback policy" as "Changes"
    And the copy preview lists "Cache lifetime (seconds)" as "Changes"
    And the copy preview offers the binding "beta-brave"
    And the copy preview refuses the binding "beta-private" with "The credential is not available to the target project."
    And the copy preview wrote nothing to project Alpha
    And the copy dialog offers "Apply changes"
    When I apply the copy
    Then the apply request echoed the preview revisions and the selected bindings
    And I see "Copied 2 settings."
    And project Alpha now overrides "routing.fallback_policy" with "first_only"

  Scenario: Changing the copy mode clears the preview
    Given I am a member of project Alpha with role project_admin
    And I am a member of project Beta with role project_member
    When I open the Settings page of project Alpha
    And I open the copy settings dialog
    And I choose "Beta" as the copy source
    And I preview the copy
    And I choose the copy mode "All current values"
    Then the copy preview is cleared
    And the copy dialog offers "Preview changes"
    And I see "Copies every current value; this project stops following the system defaults"

  Scenario: A stale copy asks for a new preview and writes nothing
    Given I am a member of project Alpha with role project_admin
    And I am a member of project Beta with role project_member
    When I open the Settings page of project Alpha
    And I open the copy settings dialog
    And I choose "Beta" as the copy source
    And I preview the copy
    And project Alpha settings change elsewhere
    And I apply the copy
    Then I see "Settings changed since the preview. Preview again."
    And project Alpha does not override "routing.fallback_policy"
