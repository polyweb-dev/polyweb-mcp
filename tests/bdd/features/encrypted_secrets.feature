@control @encrypted-secrets
Feature: Encrypted-DB secrets storage
  As a local FreeSearch operator
  I want provider keys and OAuth tokens encrypted at rest in SQLite
  So that database files and backups never carry plaintext secrets

  Scenario: AC-1 Passphrase-mode secret write is encrypted and usable
    Given an offline encrypted control API in passphrase mode
    When I write the sentinel secret for "exa" through the control API
    Then the secret response should report source "encrypted_db" with a masked fingerprint
    And the provider "exa" should probe successfully
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
    When I write all seven sentinel provider secrets through the control API
    And I complete an OAuth pairing through the stubbed vendor
    Then every secret row should decrypt to its sentinel under the correct key
    And a database-wide scan should find zero sentinel substrings
    And the OAuth metadata should hold no token material

  Scenario: AC-4 Wrong key fails closed without leaking
    Given an offline encrypted control API in passphrase mode
    When I write the sentinel secret for "exa" through the control API
    And I restart the control API with the wrong passphrase
    Then the provider "exa" should report no usable secret
    And API responses should contain no sentinel substrings

  Scenario: AC-5 No-plaintext-leak sweep across logs responses and rows
    Given an offline encrypted control API in passphrase mode with captured logs
    When I write the sentinel secret for "firecrawl" through the control API
    And I read back the provider "firecrawl" status and secret routes
    Then no captured log, response body, or database row should contain a sentinel
    And storing the same secret twice should yield different ciphertext

  Scenario: AC-6 Legacy secrets migrate once and stay intact
    Given an offline encrypted repository with legacy keyring and env secrets
    When I run the legacy secrets migration
    Then the encrypted store should resolve every migrated value
    And the legacy keyring entries should be left intact
    When I run the legacy secrets migration again
    Then no encrypted row should be overwritten

  Scenario: AC-7 OAuth lifecycle stays encrypted end to end
    Given an offline encrypted OAuth API with stubbed vendor
    When I complete an OAuth pairing through the stubbed vendor
    Then the four OAuth slots should hold only ciphertext
    And the OAuth status should be fingerprint-only
    When I disconnect OAuth
    Then the vendor revoke should have been called before local deletion
    When I disconnect OAuth again
    Then disconnecting OAuth again should stay idempotent

  Scenario: AC-8 Control-plane contracts keep their shape
    Given an offline encrypted control API in passphrase mode
    When I write the sentinel secret for "exa" through the control API
    Then the secret response should report source "encrypted_db" with a masked fingerprint
    When I delete the sentinel secret for "exa" through the control API
    Then the secret response should report missing with source "none"
    And unknown provider secret routes should return 404
    And the "keenable" provider should report keyless public presence

  Scenario: AC-9 Key rotation fails closed and is documented or commanded
    Given an offline encrypted control API in passphrase mode
    When I write the sentinel secret for "you" through the control API
    And I restart the control API with the wrong passphrase
    Then the provider "you" should report no usable secret
    And rotation should be documented or implemented as a command
