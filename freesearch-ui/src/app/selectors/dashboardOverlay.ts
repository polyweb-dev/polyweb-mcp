import { unitLabel } from "@/shared/api/units";
import type { ProviderConfig } from "@/domains/providers/model/types";
import type { DashboardQuota } from "@/domains/dashboard/model/quotaTypes";

/**
 * Overlay authoritative dashboard quota snapshots onto the provider list.
 * App-composition selector with narrow typed inputs (plan: quota overlay
 * must not make the provider domain import dashboard internals).
 * Order-independent: providers/dashboard responses may arrive either way.
 */
export function overlayDashboardQuotas(
  previous: ProviderConfig[],
  quotas: DashboardQuota[],
): ProviderConfig[] {
  if (quotas.length === 0) return previous;
  const byProvider = new Map(quotas.map((snapshot) => [snapshot.provider, snapshot]));
  return previous.map((provider) => {
    const snapshot = byProvider.get(provider.id);
    if (!snapshot) return provider;
    return {
      ...provider,
      quota: {
        ...provider.quota,
        limit: snapshot.limit,
        unit: snapshot.displayUnit ?? unitLabel(snapshot.unitKind, snapshot.displayUnit),
        confidence: snapshot.source,
        nextReset: snapshot.resetAt ?? provider.quota.nextReset,
        remaining: snapshot.remaining,
        remainingPercent: snapshot.remainingPercent,
        unitKind: snapshot.unitKind,
        displayUnit: snapshot.displayUnit,
        observedAt: snapshot.observed_at,
        window: snapshot.window,
      },
    };
  });
}
