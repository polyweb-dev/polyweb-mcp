@c2 @stub
Feature: C2 tab unification
  View-switching uses one canonical Tabs(line) control and every filter uses
  one canonical SegmentedControl, so the fleet no longer mixes underline tabs
  with boxed pills. Scope is freesearch-ui/ only: the Header nav stays plain
  buttons and no router is introduced.

  Background:
    Given I navigate to the web application

  Scenario: Playground Search/Fetch switcher uses canonical line tabs
    When I select the "Playground" header tab
    Then the playground view tabs should be canonical line tabs "Search" and "Fetch"
    And the playground tab "Search" should be selected
    And the playground tab "Fetch" should not be selected
    And the playground tabs should be linked to their panels
    And the playground should show the "Search" panel

  Scenario: Fetch tab swaps the playground hero input (button-to-tab churn)
    When I select the "Playground" header tab
    And I open the playground tab "Fetch"
    Then the playground tab "Fetch" should be selected
    And the fetch URL input should be visible
    And the playground should show the "Fetch" panel
    When I open the playground tab "Search"
    Then the playground should show the "Search" panel

  Scenario: Arrow keys move between the playground tabs
    When I select the "Playground" header tab
    And I arrow right from the playground tab "Search"
    Then the playground tab "Fetch" should have focus
    And the playground tab "Search" should be selected
    When I activate the focused playground tab
    Then the playground tab "Fetch" should be selected

  Scenario: Depth filter is an exclusive segmented group
    When I select the "Playground" header tab
    Then the depth filter should be an exclusive group of "Fast", "Balanced" and "Deep" with "Balanced" pressed

  Scenario: Depth selection moves exclusive pressed state
    When I select the "Playground" header tab
    And I choose "Deep" in the depth filter
    Then the depth filter should be an exclusive group of "Fast", "Balanced" and "Deep" with "Deep" pressed

  Scenario: Providers filter is an exclusive segmented group
    When I select the "Providers" header tab
    Then the providers filter should be an exclusive group of "All", "Search", "Fetch" and "Keyless" with "All" pressed

  Scenario: Providers Fetch filter narrows the matrix
    When I select the "Providers" header tab
    And I choose "Fetch" in the providers filter
    Then the providers matrix should show 4 provider rows
    And the providers matrix should not contain "Brave Search"

  Scenario: Activity filter is an exclusive segmented group
    When I select the "Activity" header tab
    Then the activity filter should be an exclusive group of "All", "Search" and "Fetch" with "All" pressed

  Scenario: Activity Fetch filter keeps only fetch events
    When I select the "Activity" header tab
    And I choose "Fetch" in the activity filter
    Then the activity list should contain provider "Keenable"
    And the activity list should not contain provider "Brave Search"

  Scenario: Routing and Settings tabs stay canonical line tabs
    When I select the "Routing" header tab
    Then the routing tabs should remain canonical line tabs "Strategy", "Simulator", "Ranks" and "Resilience"
    When I select the "Settings" header tab
    Then the settings tabs should remain canonical line tabs "Providers", "Keys" and "Failover"

  Scenario: No hand-rolled mimics in tab and filter slots
    When I select the "Playground" header tab
    Then the playground should expose no button named "Fetch" while in search mode
    And every playground filter toggle should live inside a group

  Scenario: Header nav stays plain buttons and tab switches never change the URL
    When I select the "Playground" header tab
    Then the header navigation should expose zero tab roles
    When I open the playground tab "Fetch"
    Then the page URL should be unchanged
