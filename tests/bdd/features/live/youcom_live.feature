@live @control @vault-live
Feature: Live You.com search and fetch through the vault
  As a local Polyweb operator
  I want a manual live check that a vault-stored You.com key runs search+fetch
  So that vault wiring is proven end to end without hardcoding credentials

  # Manual-only: the default behave run excludes @live (pyproject
  # [tool.behave] default_tags = ["not @live"]); select it explicitly with
  # `uv run behave --tags="@live and @vault-live"`. Requires a real
  # You.com key in the harness env (POLYWEB_YOU_API_KEY) plus an
  # encryption passphrase (POLYWEB_ENCRYPTION_KEY). Skips gracefully
  # when the key is absent; never hardcodes a real key.

  @live
  Scenario: Live you.com search then fetch through the vault
    Given a live vault-backed You.com control API
    When I run a live vault search for "Python modern async programming" with limit 3
    And I fetch the first live vault result URL
    Then the live vault search and fetch should succeed
    And live vault logs and responses should contain no key material
