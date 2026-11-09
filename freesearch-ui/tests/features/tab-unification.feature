@c2 @stub
Feature: C2 tab unification
  View-switching uses one canonical Tabs(pill) control and every filter uses
  one canonical SegmentedControl, so the fleet shares the provider-page pill
  look for view-switching. Scope is freesearch-ui/ only: the Header nav stays plain
  buttons and no router is introduced.

  Playground and Activity are project sections (U2); the default stubbed
  session works in project Alpha.

  Background:
    Given I navigate to the web application
    And the stubbed session works in project Alpha

  Scenario: Playground Search/Fetch switcher uses canonical pill tabs
    When I open the "playground" section of project Alpha
    Then the playground view tabs should be canonical pill tabs "Search" and "Fetch"
    And the playground tab "Search" should be selected
    And the playground tab "Fetch" should not be selected
    And the playground tabs should be linked to their panels
    And the playground should show the "Search" panel

  Scenario: Fetch tab swaps the playground composer (pill switcher)
    When I open the "playground" section of project Alpha
    And I open the playground tab "Fetch"
    Then the playground tab "Fetch" should be selected
    And the fetch URL input should be visible
    And the playground should show the "Fetch" panel
    When I open the playground tab "Search"
    Then the playground should show the "Search" panel

  Scenario: Arrow keys move between the playground tabs
    When I open the "playground" section of project Alpha
    And I arrow right from the playground tab "Search"
    Then the playground tab "Fetch" should have focus
    And the playground tab "Search" should be selected
    When I activate the focused playground tab
    Then the playground tab "Fetch" should be selected

  # PG-S5 RETIRED (number-of-results contract): the Depth Fast/Balanced/Deep
  # SegmentedControl is deleted from the playground — a labeled
  # "Number of results" number input (default 6) replaces it. The two
  # scenarios below asserted the deleted Depth group and cannot survive.
  # Scenario: Depth filter is an exclusive segmented group
  #   When I select the "Playground" header tab
  #   Then the depth filter should be an exclusive group of "Fast", "Balanced" and "Deep" with "Balanced" pressed
  #
  # Scenario: Depth selection moves exclusive pressed state
  #   When I select the "Playground" header tab
  #   And I choose "Deep" in the depth filter
  #   Then the depth filter should be an exclusive group of "Fast", "Balanced" and "Deep" with "Deep" pressed

  Scenario: Results count is a number input and no Depth filter remains
    When I open the "playground" section of project Alpha
    Then the results count should be a number input defaulting to "6"
    And the playground should expose no depth filter

  # P1-FINAL RETIRED (DROP fleet filter ruling + PillTabs.c2r filter-case
  # retirement): the standalone Providers page and its All/Search/Fetch/
  # Keyless capability filter are gone — the Settings Providers tab holds ONE
  # merged table with no filter. The two scenarios below asserted the dropped
  # filter and cannot survive the merge.
  # Scenario: Providers filter is an exclusive segmented group
  #   When I select the "Providers" header tab
  #   Then the providers filter should be an exclusive group of "All", "Search", "Fetch" and "Keyless" with "All" pressed
  #
  # Scenario: Providers Fetch filter narrows the matrix
  #   When I select the "Providers" header tab
  #   And I choose "Fetch" in the providers filter
  #   Then the providers matrix should show 4 provider rows
  #   And the providers matrix should not contain "Brave Search"

  Scenario: Activity filter is an exclusive segmented group
    When I open the "activity" section of project Alpha
    Then the activity filter should be an exclusive group of "All", "Search" and "Fetch" with "All" pressed

  Scenario: Activity Fetch filter keeps only fetch events
    When I open the "activity" section of project Alpha
    And I choose "Fetch" in the activity filter
    Then the activity list should contain provider "Keenable"
    And the activity list should not contain provider "Brave Search"

  Scenario: The provider catalog has no retired Keys tab
    When I select the "Providers" header tab
    Then the settings page should not expose a "Keys" tab

  Scenario: No hand-rolled mimics in tab and filter slots
    When I open the "playground" section of project Alpha
    Then the playground should expose no button named "Fetch" while in search mode
    And every playground filter toggle should live inside a group

  Scenario: Header nav stays plain buttons and tab switches never change the URL
    When I open the "playground" section of project Alpha
    Then the header navigation should expose zero tab roles
    When I open the playground tab "Fetch"
    Then the page URL should be unchanged
