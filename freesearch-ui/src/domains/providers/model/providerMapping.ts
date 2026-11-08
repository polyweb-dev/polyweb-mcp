import type { BackendProviderStatus } from "@/domains/providers/api/wire";
import type { ProviderConfig } from "./types";
import { catalogEntryForId } from "./catalog";
import { mapBackendHealth, mergeProviderStatus } from "@/services/api/mappers";

function withHealthTimestamp(provider: ProviderConfig, row: BackendProviderStatus): ProviderConfig {
  const checkedAt = row.health_checked_at;
  const healthCheckedAt = typeof checkedAt === "string" && Number.isFinite(Date.parse(checkedAt)) ? checkedAt : null;
  return {
    ...provider,
    healthCheckedAt,
    ...(row.call_cost_usd !== undefined ? { callCostUsd: row.call_cost_usd } : {}),
    keylessCallCostUsd: row.keyless_call_cost_usd ?? {},
    capabilities: [
      ...provider.capabilities.filter((capability) => capability !== "keyless_tier"),
      ...(Object.keys(row.keyless_call_cost_usd ?? {}).length > 0 ? ["keyless_tier" as const] : []),
    ],
    ...(healthCheckedAt !== null && row.health !== null
      ? { healthStatus: mapBackendHealth(row.health, "closed") }
      : {}),
  };
}

export function mapProviderRows(rows: BackendProviderStatus[]): ProviderConfig[] {
  return rows
    .map((row) => {
      const entry = catalogEntryForId(row.provider_id);
      return entry ? withHealthTimestamp(mergeProviderStatus(entry, row), row) : null;
    })
    .filter((row): row is ProviderConfig => row !== null);
}

export function updateProviderFromWire(
  previous: ProviderConfig[],
  row: BackendProviderStatus,
): ProviderConfig[] {
  const entry = catalogEntryForId(row.provider_id);
  if (!entry) return previous;
  const mapped = withHealthTimestamp(mergeProviderStatus(entry, row), row);
  return previous.map((provider) => (provider.id === mapped.id ? mapped : provider));
}
