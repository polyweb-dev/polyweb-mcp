@database @migration @quota
Feature: Alpha database lifecycle across Git worktrees
  As a FreeSearch operator
  I want each checkout database created at the settled alpha baseline
  So that an incompatible database is never silently rewritten and no checkout touches another

  Scenario: A fresh database is created at the alpha baseline and validates
    Given no FreeSearch database exists at the selected path
    When FreeSearch prepares the selected database
    Then the selected database is at the alpha baseline revision
    And the selected database passes schema and foreign-key validation

  Scenario: A database from an unknown revision is rejected and left unchanged
    Given a FreeSearch database left at the unknown revision "0009_provider_credentials"
    When FreeSearch tries to prepare the selected database
    Then FreeSearch refuses the database with a compatibility message naming "0009_provider_credentials"
    And the refused database bytes are unchanged

  Scenario: Creating a worktree database never touches the main checkout database
    Given a main checkout database at the unknown revision "0009_provider_credentials"
    And no FreeSearch database exists at the worktree path
    When FreeSearch prepares the worktree database
    Then the worktree database is at the alpha baseline revision
    And the main checkout database is byte-for-byte unchanged
