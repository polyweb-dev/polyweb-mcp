@control @encrypted-secrets
Feature: Encrypted-DB secrets storage
  As a local Polyweb operator
  I want provider keys and OAuth tokens encrypted at rest in SQLite
  So that database files and backups never carry plaintext secrets

  Scenario: AC-1 Passphrase-mode secret write is encrypted and usable
    Given an offline encrypted control API in passphrase mode
    When I write the sentinel secret for "exa" through the control API
    Then the vault key response should contain only current metadata
    And the provider "exa" should serve a project search using the vault key
    And the database file should hold only ciphertext for "exa"

  Scenario: AC-2 Auto-generated key file has strict permissions and is reused
    Given an offline encrypted control API in auto-generate mode
    When I write the sentinel secret for "tavily" through the control API
    Then a key file should exist with mode 0600 under a 0700 directory
    When I restart the control API on the same database
    Then the secret for "tavily" should still resolve
    And the key file should be unchanged

  Scenario: AC-3 All provider keys and OAuth tokens rest as ciphertext only
    Given an offline encrypted control API in passphrase mode
    When I write all eight sentinel provider secrets through the control API
    And I complete an OAuth pairing through the stubbed vendor
    Then every secret row should decrypt to its sentinel under the correct key
    And a database-wide scan should find zero sentinel substrings
    And the OAuth metadata should hold no token material

  Scenario: AC-4 Wrong key fails closed without leaking
    Given an offline encrypted control API in passphrase mode
    When I write the sentinel secret for "exa" through the control API
    And I create a project pool for the sentinel key
    And I restart the control API with the wrong passphrase
    Then the provider "exa" should report no usable secret
    And API responses should contain no sentinel substrings

  Scenario: AC-5 No-plaintext-leak sweep across logs responses and rows
    Given an offline encrypted control API in passphrase mode with captured logs
    When I write the sentinel secret for "firecrawl" through the control API
    And I read back the vault key and its pools for "firecrawl"
    Then no captured log, response body, or database row should contain a sentinel
    And storing the same secret twice should yield different ciphertext

  Scenario: AC-6 Vault deletes win via tombstone across a restart
    Given an offline encrypted control API in passphrase mode
    When I write the sentinel secret for "exa" through the control API
    And I delete the sentinel secret for "exa" through the control API
    Then the secret for "exa" should stay missing with a tombstone
    When I restart the control API on the same database
    Then the secret for "exa" should stay missing with a tombstone

  Scenario: AC-7 OAuth lifecycle stays encrypted end to end
    Given an offline encrypted OAuth API with stubbed vendor
    When I complete an OAuth pairing through the stubbed vendor
    Then the four OAuth slots should hold only ciphertext
    And the OAuth status should contain only non-secret metadata
    When I disconnect OAuth
    Then the vendor revoke should have been called and local tokens deleted
    When I disconnect OAuth again
    Then disconnecting OAuth again should stay idempotent

  Scenario: AC-8 Control-plane contracts keep their shape
    Given an offline encrypted control API in passphrase mode
    When I write the sentinel secret for "exa" through the control API
    Then the vault key response should contain only current metadata
    When I create a project pool for the sentinel key
    Then the pool response should match the current vault contract
    When I update and rotate the vault key with its project pool
    When I delete the sentinel secret for "exa" through the control API
    Then the vault delete response should identify the deleted project pool
    And retired credential write routes should be unavailable
