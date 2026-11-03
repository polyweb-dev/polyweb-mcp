@system-capacity @stub
Feature: Capacity
  The Capacity page (/system/capacity) lists upstream pools with readable
  limits and their credential links under system.pools.manage, and edits each
  project's allocations under system.allocations.manage. Every allocation
  carries one explanation: a strict cap, loans with a guaranteed share and
  borrowing, or best effort for a zero base. An infeasible allocation shows the
  server's reason. Served by the in-memory stub.

  Background:
    Given the projects backend is stubbed for a system administrator
    And the provider configuration is stubbed
    And I am a member of project Alpha with role project_admin
    And I am a member of project Beta with role project_member

  Scenario: Pools show readable limits and a new pool can be created
    When I open the workspace page "/projects"
    And I follow the "Capacity" sidebar link
    Then I see the heading "Capacity"
    And the pools table lists "Tavily shared pool" with "10 per second (token bucket)"
    And the pools table lists "Brave shared pool" with "120 per minute (fixed window)"
    When I add a pool with:
      | field               | value            |
      | Provider            | Tavily           |
      | Label               | Tavily burst pool |
      | Upstream scope      | credential       |
      | Pool key            | tavily-burst     |
      | Algorithm           | Rolling window   |
      | Window seconds      | 3600             |
      | Limit               | 1000             |
      | Max concurrency     | 4                |
      | Max queued requests | 20               |
    Then the last pool create request sent:
      """
      {
        "provider_type": "tavily",
        "label": "Tavily burst pool",
        "upstream_scope": "credential",
        "pool_key": "tavily-burst",
        "constraints": [{ "algorithm": "rolling_window", "window_seconds": 3600, "limit": 1000 }],
        "max_concurrency": 4,
        "max_queued_requests": 20
      }
      """
    And the pools table lists "Tavily burst pool" with "1000 per hour (rolling window)"

  Scenario: A system credential can be linked to a pool and unlinked
    When I open the workspace page "/system/capacity"
    And I link "Shared Brave" for "search" to the pool "Brave shared pool"
    Then the pool "Brave shared pool" links "Shared Brave" for "search"
    When I remove the link of "Shared Brave"
    Then the pool "Brave shared pool" has no links

  Scenario: Allocations explain strict caps, loans and best effort per project
    When I open the workspace page "/system/capacity"
    And I show the allocations of project Alpha
    Then the capacity allocations read:
      | badge         | text                                                                                                                                                  |
      | Loans enabled | Guaranteed 5 per second under contention (weight 2). Can borrow up to 10 per second when the pool is idle. The pool limit always applies. |
      | Strict cap    | Up to 60 per minute. Unused capacity of other projects is not lent.                                                                                   |
    When I show the allocations of project Beta
    Then the capacity allocations read:
      | badge       | text                                                          |
      | Best effort | No guaranteed share. Runs only when the pool has idle capacity. |

  Scenario: Switching an allocation from a strict cap to loans sends the max rate and weight
    When I open the workspace page "/system/capacity"
    And I show the allocations of project Alpha
    And I edit the allocation "Brave shared pool search"
    Then the allocation form hides "Max rate"
    When I choose the allocation mode "Loans enabled"
    Then the allocation form shows "Max rate"
    When I fill the allocation form with:
      | field    | value |
      | Max rate | 120   |
      | Weight   | 3     |
    And I save the allocation
    Then the last allocation write for "Brave shared pool" "search" sent:
      """
      { "base_rate": 60, "rate_window_seconds": 60, "borrow_enabled": true, "max_rate": 120, "weight": 3 }
      """
    And the capacity allocations read:
      | badge         | text                                                                                                                                    |
      | Loans enabled | Guaranteed 60 per minute under contention (weight 3). Can borrow up to 120 per minute when the pool is idle. The pool limit always applies. |

  Scenario: A zero base rate needs best effort before anything is sent
    When I open the workspace page "/system/capacity"
    And I show the allocations of project Alpha
    And I add an allocation with:
      | field          | value              |
      | Pool           | Tavily shared pool |
      | Operation      | fetch              |
      | Base rate      | 0                  |
      | Window seconds | 1                  |
    And I save the allocation
    Then I see "A zero base rate needs best effort."
    And no allocation write was sent
    When I tick best effort
    And I save the allocation
    Then the last allocation write for "Tavily shared pool" "fetch" sent:
      """
      { "base_rate": 0, "rate_window_seconds": 1, "borrow_enabled": false, "best_effort": true }
      """

  Scenario: An infeasible allocation shows the server's reason
    When I open the workspace page "/system/capacity"
    And I show the allocations of project Alpha
    And I edit the allocation "Tavily shared pool search"
    And I fill the allocation form with:
      | field     | value |
      | Base rate | 20    |
      | Max rate  | 25    |
    And I save the allocation
    Then I see "Not feasible: Guaranteed rates of all projects exceed the pool limit of 10 per 1 seconds."

  Scenario: With only pools.manage the allocations are read-only
    Given the projects backend is stubbed with system permissions "system.pools.manage"
    And the provider configuration is stubbed
    When I open the workspace page "/system/capacity"
    Then I see the heading "Capacity"
    And the Capacity page offers pool editing but no allocation editing
    And the Primary navigation lists exactly "Capacity, Projects, Account"
