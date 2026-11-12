---
title: System providers and quotas
description: Turn providers on or off for every project and watch provider balances and budgets.
---

Two pages in the sidebar's system section cover the whole installation: **Providers** and **Quotas**. Only users with system access see them. Project members use [Project providers](/dashboard/project-providers/) and [Usage](/dashboard/usage/) instead.

## Manage the provider catalog

**Providers** opens with the heading "The provider catalog and failure policy for every project". The table has one row per provider.

| Column | Meaning |
| --- | --- |
| **Provider** | The provider, with **Custom** or **No key needed** tags where they apply. |
| **Endpoint** | The provider's base address. |
| **Cost per call** | Catalog price for search and fetch, with keyless access shown separately. |
| **Health** | The last connection test. |
| **Search**, **Fetch** | Switches for each operation. A dash means the provider doesn't support it. |
| **On** | Master switch. Off removes the provider from every project. |

Turning a switch off takes effect for all projects. Without control-edit access you see the values as plain text.

To test a provider, select the refresh icon in its **Health** cell, review the endpoint and capabilities, and select **Test**. The result shows the status and latency, or the failure message. Opening the dialog doesn't call the provider.

### Set the failure policy

Under the table, **When a provider fails** has two settings.

| Setting | Meaning |
| --- | --- |
| **Fallback** | When on, a failed request tries the next provider in the project's order. When off, each request tries one provider. |
| **Max attempts** | How many providers one request may try, first one included (1 to 10). Shown while Fallback is on. |

Provider keys aren't set here. They live in the vault, under **Keys and pools**. See [Provider keys and pools](/dashboard/provider-keys/).

## Watch quotas

**Quotas** opens with "Provider balances and allowances across all projects". It has three parts.

1. **Allowance left** has one card per provider that reports limits, with rate bars and remaining balance.
2. **Key balances** lists balances per key for providers with more than one key.
3. **Usage totals** lists **Provider**, **Searches**, **URLs fetched**, **Cost** and **p95** (95th-percentile latency) for the whole installation. It reads "No usage recorded yet" until calls happen.

Each card has a **Refresh** button where the provider reports usage. The card's actions menu has:

- **Set balance**: record the balance you see on the provider's own dashboard, as an estimate. Fill in **Billing start**, **Billing end** (both `YYYY-MM-DD`), **Allowance** and either **Credits left** or **Balance remaining**, then select **Save balance**. The end date must not be before the start date.
- **Set budget**: set a local USD ceiling with **Search budget (USD)** and, where the provider supports fetch, **Fetch budget (USD)**. Polyweb stops that provider once the budget is used.
- **Balance history**: review earlier balance records.

Brave supports search only, so it has no fetch budget or fetch limits. For how rate limits and budgets differ, see [Rate limits and budgets](/concepts/limits-and-budgets/).

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| **Providers** or **Quotas** is missing from the sidebar | Your account has no system access. Ask a system admin. |
| Switches show **On** or **Off** text, not switches | You have read access only. |
| A connection test fails | Check the provider's key in **Keys and pools**, then test again. |
