---
title: Rate limits and budgets
description: The difference between rate limits and budgets, and what 402 and 429 mean.
---

Two separate limits can stop a provider call. A rate limit controls how fast you call. A budget controls how much you can spend. They fail differently, so handle them differently.

| | Rate limit | Budget |
| --- | --- | --- |
| Measures | Requests per second or minute | Credits, dollars, or requests per day or month |
| Typical status | `429` with `Retry-After` | `402` |
| What to do | Wait, then retry with backoff | Top up, wait for the reset, or use another provider |
| Retry now? | Yes, after the wait | No |

Keyless tiers, such as Keenable's free tier, have a rate limit and no budget. Paid keys have both.

## Where limits come from

The provider enforces its own limits on your provider key, and Polyweb also checks a local limit before it spends a metered call. Either can reject a request. Polyweb returns a rate rejection as `429` with a `Retry-After` header, and a spent budget or missing access as `402`.

Brave puts both cases inside `429`. A `RATE_LIMITED` code means you went too fast, and `QUOTA_LIMITED` means your credits are gone. A `402` from Tinyfish Search means the account lacks Search access, not that you ran out of money.

When Polyweb itself is busy, it can also answer `429` with `Retry-After`. A failure of the limit store returns `503`, before any provider is called.

The per-provider numbers (rates, budget model, keyless access) are in [Provider reference](/providers/reference/).

## What the errors look like

A rate limit:

```json
{
  "provider": "tinyfish",
  "code": "RATE_LIMIT_EXCEEDED",
  "message": "slow down and retry",
  "retryable": true,
  "status_code": 429
}
```

A spent budget:

```json
{
  "provider": "exa",
  "code": "NO_MORE_CREDITS",
  "message": "team credits are spent",
  "retryable": false,
  "status_code": 402
}
```

Vendor error codes differ by provider. Branch on `status_code` and `retryable` first. Polyweb already falls back to another provider when routing allows it (see [Routing](/concepts/routing/)).

## Watching spend

The cost of a call varies by provider and options, so read it from the result instead of counting calls. The [Usage](/dashboard/usage/) page totals cost and calls per provider for a project. System admins see allowances across all projects under [System providers and quotas](/dashboard/system-admin/).

<!-- TODO(owner): LIMITS.md proposes a unified "SC" unit (1 SC-search = 1 standard search call). It is research only and is not in the code, so it is left out here. -->

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `429` on bursts of calls | Rate limit | Wait for `Retry-After`, then retry with backoff |
| `402` | Budget spent or no access | Top up the provider account, wait for its reset, or route to another provider |
| `429` with Brave code `QUOTA_LIMITED` | Brave credits are used up | Add credits. Retrying will not help |
| `402` from Tinyfish Search | Account lacks Search access | Enable Search on the Tinyfish account |
| Fetch rejected for Brave | Brave has no fetch | Route fetch to another provider |
| `503` before a call | Limit store unavailable | Retry later and check the API server logs |

## Next steps

- [Provider reference](/providers/reference/) lists limits per provider.
- [Troubleshooting](/reference/troubleshooting/) covers other common failures.
