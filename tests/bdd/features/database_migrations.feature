@database @migration @quota
Feature: Safe database migration across Git worktrees
  As a FreeSearch operator
  I want each checkout database adopted independently
  So that merging code never replaces or silently rewrites another checkout's data

  Scenario: A pre-Alembic database is backed up and upgraded without rewriting rows
    Given a pre-Alembic database with historical usage and quota rows
    When I run the FreeSearch database migration
    Then the database should be at the canonical Alembic head
    And the historical rows and native units should be unchanged
    And an integrity-checked pre-migration backup should exist

  Scenario: Upgrading a worktree database does not touch the main checkout database
    Given separate main and worktree databases with distinct historical rows
    When I run the FreeSearch database migration for the worktree
    Then only the worktree database should be at the canonical Alembic head
    And the main checkout database bytes should be unchanged
