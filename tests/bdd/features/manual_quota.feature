@control
Feature: Manual billing-anchor quota overlay
  As a local Polyweb operator
  I want to record dashboard billing figures per provider
  So that the dashboard shows an ESTIMATED balance without steering routing

  Scenario: Brave billing anchor estimates remaining percent and clears
    Given an offline manual-quota API with stub adapters
    When I set the Brave manual quota to allowance "5.00" usage "0.88" for August 2026
    Then the manual quota should be ESTIMATED with remaining "4.12" and percent "82.4"
    When I update the Brave manual quota usage to "2.50"
    Then the manual quota percent should adjust to "50"
    When I clear the Brave manual quota
    Then the manual quota should be missing
