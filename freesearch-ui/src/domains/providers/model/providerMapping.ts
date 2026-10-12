import type { BackendProviderStatus } from "@/domains/providers/api/wire";
import type { ProviderConfig } from "./types";
import { catalogEntryForId } from "./catalog";
import { mergeProviderStatus } from "@/services/api/mappers";

export function mapProviderRows(rows: BackendProviderStatus[]): ProviderConfig[] {
  return rows
    .map((row) => {
      const entry = catalogEntryForId(row.provider_id);
      return entry ? mergeProviderStatus(entry, row) : null;
    })
    .filter((row): row is ProviderConfig => row !== null)
    .sort((a, b) => a.priority - b.priority);
}

export function updateProviderFromWire(
  previous: ProviderConfig[],
  row: BackendProviderStatus,
): ProviderConfig[] {
  const entry = catalogEntryForId(row.provider_id);
  if (!entry) return previous;
  const mapped = mergeProviderStatus(entry, row);
  return previous
    .map((provider) => (provider.id === mapped.id ? mapped : provider))
    .sort((a, b) => a.priority - b.priority);
}

export interface ProviderPriorityPatch {
  provider: ProviderConfig;
  priority: number;
}

export function priorityPatchesForMove(
  sorted: ProviderConfig[],
  sourceIndex: number,
  targetIndex: number,
): ProviderPriorityPatch[] {
  if (
    sourceIndex < 0 ||
    sourceIndex >= sorted.length ||
    targetIndex < 0 ||
    targetIndex >= sorted.length ||
    sourceIndex === targetIndex
  ) {
    return [];
  }
  const reordered = [...sorted];
  const [moving] = reordered.splice(sourceIndex, 1);
  if (!moving) return [];
  reordered.splice(targetIndex, 0, moving);
  return reordered
    .map((provider, rankIndex) => {
      const priority = rankIndex + 1;
      return provider.priority === priority ? null : { provider, priority };
    })
    .filter((patch): patch is ProviderPriorityPatch => patch !== null);
}
