@api_keys
Feature: Project API keys for machine clients
  As a project administrator
  I want project API keys for my machine clients
  So that agents run search and fetch in my project without a human account

  Scenario: A project API key executes in its own project until it is revoked
    Given an offline API with a project administrator and a counting provider
    When the project administrator issues an API key through the API
    Then the key should be shown once and absent from the key list
    And the key should search its project over REST and MCP
    When the project administrator revokes the key
    Then the next REST and MCP calls with the key should fail without provider calls
    And the project administrator should still search the project without a key
