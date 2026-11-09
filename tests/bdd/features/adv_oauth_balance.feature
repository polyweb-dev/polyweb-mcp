@control @adv-oauth @oauth-balance
Feature: Parallel OAuth balance as authoritative USD quota
  As a Polyweb operator
  I want the OAuth balance to surface as exact USD remaining-only quota
  So that the dashboard never mixes floats, invoices, or stale seeds

  Background:
    Given an offline Parallel OAuth API with stubbed vendor

  Scenario Outline: Balance net converts to exact USD
    Given a stubbed vendor balance of <credit> credit and <pending> pending cents
    When I connect OAuth, run the bounded balance poll, and read the dashboard
    Then the Parallel quota should be authoritative USD "<usd>" with no limit

    Examples:
      | credit | pending | usd   |
      | 1250   | 250     | 10.00 |
      | 101    | 0       | 1.01  |
      | 1      | 0       | 0.01  |
      | 100    | 500     | 0     |

  Scenario: Invoiced accounts record nothing
    Given a stubbed invoiced vendor balance
    When I connect OAuth, run the bounded balance poll, and read the dashboard
    Then the Parallel quota entry should be missing

  Scenario: Live balance outranks seed and manual anchors
    Given a seeded and anchored account with live credit 1250 pending 250
    When I connect OAuth, run the bounded balance poll, and read the dashboard
    Then the live balance should win as authoritative USD "10.00"

  Scenario: Balance polling respects TTL and failure backoff
    Given a connected Parallel OAuth session
    When I run the bounded balance poll repeatedly through failures
    Then vendor balance polls should stay bounded
