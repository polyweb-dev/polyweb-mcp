@project-settings @stub
Feature: Project settings
  A project's Settings page shows every Routing, Execution and Trace policy
  field with its effective value, where it comes from (System default, Project
  override, Limited by system), the system default and the system limit. With
  settings.write a field can be overridden or reset to inherit; a section save
  sends only the changed fields with the expected revision, and a stale
  revision asks for a reload. Copying settings from another project is a
  revision-bound preview then apply; the preview writes nothing. Served by the
  in-memory stub.

  Background:
    Given the projects backend is stubbed
    And the provider configuration is stubbed

  Scenario: Fields show their effective value, provenance, system default and system limit
    Given I am a member of project Alpha with role project_admin
    When I open the Settings page of project Alpha
    Then I see the heading "Settings"
    And I see the heading "Routing"
    And I see the heading "Execution"
    And I see the heading "Trace policy"
    And the settings field "routing.max_attempts" shows "Project override"
    And the settings field "routing.max_attempts" shows "System default: 3"
    And the settings field "routing.fallback_policy" shows "System default"
    And the settings field "trace.retention_days" shows "Limited by system"
    And the settings field "trace.retention_days" shows "System limit: 90"
    And the settings field "trace.retention_days" shows "Your override exceeds the system limit; the system limit applies."
    And the trace policy summary reads "New traces: 100% sampled, Metadata only, Standard redaction, kept 90 days."
    And the "Payload detail" option "Full payloads" is disabled with "The system allows metadata only."

  Scenario: A section save sends only the changed fields and Inherit sends null
    Given I am a member of project Alpha with role project_admin
    When I open the Settings page of project Alpha
    And I set the settings field "execution.max_fanout_concurrency" labelled "Fan-out concurrency" to "8"
    And I save the "Execution" settings section
    Then I see "Settings saved."
    And the last settings save sent exactly:
      """
      { "expected_revision": 2, "execution": { "max_fanout_concurrency": 8 } }
      """
    And the settings field "execution.max_fanout_concurrency" shows "Project override"
    When I inherit the settings field "Max attempts"
    And I save the "Routing" settings section
    Then the last settings save sent exactly:
      """
      { "expected_revision": 3, "routing": { "max_attempts": null } }
      """
    And the settings field "routing.max_attempts" shows "System default"

  Scenario: A stale save asks to reload the settings
    Given I am a member of project Alpha with role project_admin
    When I open the Settings page of project Alpha
    And project Alpha settings change elsewhere
    And I set the settings field "execution.max_fanout_concurrency" labelled "Fan-out concurrency" to "8"
    And I save the "Execution" settings section
    Then I see "Settings changed since you opened them."
    When I reload the settings
    Then the settings were read again
    And I do not see "Settings changed since you opened them."

  Scenario: A strict system redaction disables the Standard option
    Given the system requires strict redaction
    And I am a member of project Alpha with role project_admin
    When I open the Settings page of project Alpha
    Then the trace policy summary reads "New traces: 100% sampled, Metadata only, Strict redaction, kept 90 days."
    And the "Redaction" option "Standard" is disabled with "The system requires strict redaction."

  Scenario: A project member sees settings read-only without copy
    Given I am a member of project Alpha with role project_member
    When I open the Settings page of project Alpha
    Then I see "You can view these settings. Ask a project administrator to change them."
    And the settings field "routing.max_attempts" shows "Project override"
    And the settings page offers no editing controls

  Scenario: Copy previews first, then applies the preview's revisions and selected bindings
    Given I am a member of project Alpha with role project_admin
    And I am a member of project Beta with role project_member
    When I open the Settings page of project Alpha
    And I open the copy settings dialog
    Then the copy Apply button is disabled
    When I choose "Beta" as the copy source
    And I preview the copy
    Then the copy preview lists "Fallback policy" as "Changes"
    And the copy preview lists "Cache lifetime (seconds)" as "Changes"
    And the copy preview offers the binding "beta-brave"
    And the copy preview refuses the binding "beta-private" with "The credential is not available to the target project."
    And the copy preview wrote nothing to project Alpha
    And the copy Apply button is enabled
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
    And I choose the copy mode "Effective snapshot"
    Then the copy preview is cleared
    And the copy Apply button is disabled
    And I see "Pins current values and stops inheritance."

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
