@fanout @search
Feature: All-providers fanout search with ranked fusion
  As an API consumer
  I want a query fanned out to every eligible provider at once
  So that I receive deduplicated, RRF-ranked results from all engines

  Background:
    Given an offline fanout search harness

  @smoke
  Scenario: Fusion happy path fuses overlapping hits from two providers
    Given the following fanout provider registry:
      | provider | urls                                                                                       | behavior |
      | exa      | https://example.com/exa-exclusive, https://example.com/consensus-page?utm_source=exa       | succeed  |
      | brave    | https://example.com/brave-exclusive, https://www.example.com/consensus-page/               | succeed  |
    When I submit a fanout search for "fusion probe" with limit 10
    Then the response provider should be "aggregated"
    And the participating providers should be "exa, brave"
    And the fused result count should be 3
    And the top fused result URL should contain "consensus-page"
    And the top fused result should fuse sources "exa, brave"
    And every fused result should carry source attribution and fusion scores

  Scenario: Partial failure still returns the surviving providers results
    Given the following fanout provider registry:
      | provider | urls                            | behavior |
      | flaky    | https://example.com/never       | fail     |
      | reliable | https://example.com/reliable    | succeed  |
    When I submit a fanout search for "fusion probe" with limit 10
    Then the response provider should be "reliable"
    And the participating providers should be "reliable"
    And the fused result count should be 1

  Scenario: Total failure surfaces an all-providers-failed error
    Given the following fanout provider registry:
      | provider | urls                       | behavior |
      | flaky-a  | https://example.com/never  | fail     |
      | flaky-b  | https://example.com/never  | fail     |
    When I submit a fanout search for "fusion probe" with limit 10
    Then the fanout search should fail with status 500 containing "all search providers failed"

  Scenario: Provider allow-list restricts fanout participation
    Given the following fanout provider registry:
      | provider | urls                         | behavior |
      | exa      | https://example.com/exa-only | succeed  |
      | brave    | https://example.com/brave-only | succeed  |
    When I submit a fanout search for "fusion probe" restricted to providers "exa"
    Then the response provider should be "exa"
    And the participating providers should be "exa"
    And the fused result count should be 1

  Scenario: Allow-list with no eligible provider reports no-eligible
    Given the following fanout provider registry:
      | provider | urls                         | behavior |
      | exa      | https://example.com/exa-only | succeed  |
      | brave    | https://example.com/brave-only | succeed  |
    When I submit a fanout search for "fusion probe" restricted to providers "ghost"
    Then the fanout search should fail with status 503 containing "no eligible provider"
