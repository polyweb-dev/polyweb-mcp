import { useCallback, useRef } from "react";
import { apiService } from "@/services/api/freesearchApi";
import { errorMessage } from "@/shared/api/http";
import type { ProviderConfig } from "@/domains/providers/model/types";
import { toBackendId } from "@/domains/providers/api/idMapping";
import {
  updateProviderFromWire,
  priorityPatchesForMove,
  type ProviderPriorityPatch,
} from "@/domains/providers/model/providerMapping";
import type { ShowToast } from "./context";

interface PriorityDeps {
  providers: ProviderConfig[];
  setProviders: React.Dispatch<React.SetStateAction<ProviderConfig[]>>;
  refreshProviders: () => Promise<void>;
  showToast: ShowToast;
}

async function restoreProviderPriorities(completed: ProviderPriorityPatch[]): Promise<void> {
  for (const { provider } of [...completed].reverse()) {
    try {
      await apiService.patchProvider(toBackendId(provider.id), { priority: provider.priority });
    } catch {
      // The authoritative refresh remains the fallback if compensation fails.
    }
  }
}

export function useProviderPriority({ providers, setProviders, refreshProviders, showToast }: PriorityDeps) {
  const priorityMoveInFlight = useRef(false);

  const updateProviderPriority = useCallback(
    async (id: string, newPriority: number): Promise<boolean> => {
      try {
        const wire = await apiService.patchProvider(toBackendId(id), { priority: newPriority });
        setProviders((previous) => updateProviderFromWire(previous, wire));
        return true;
      } catch (error) {
        showToast(errorMessage(error, "Unable to update provider priority"), "error");
        return false;
      }
    },
    [setProviders, showToast],
  );

  const moveProviderPriority = useCallback(
    async (id: string, direction: "up" | "down") => {
      if (priorityMoveInFlight.current) return;

      const sorted = [...providers].sort((a, b) => a.priority - b.priority);
      const index = sorted.findIndex((provider) => provider.id === id);
      const targetIndex = direction === "up" ? index - 1 : index + 1;
      if (index < 0 || targetIndex < 0 || targetIndex >= sorted.length) return;

      const patches = priorityPatchesForMove(sorted, index, targetIndex);
      const completed: ProviderPriorityPatch[] = [];
      priorityMoveInFlight.current = true;

      try {
        for (const patch of patches) {
          const wire = await apiService.patchProvider(toBackendId(patch.provider.id), {
            priority: patch.priority,
          });
          completed.push(patch);
          setProviders((previous) => updateProviderFromWire(previous, wire));
        }
        await refreshProviders();
      } catch (error) {
        await restoreProviderPriorities(completed);
        await refreshProviders();
        showToast(errorMessage(error, "Unable to move provider priority"), "error");
      } finally {
        priorityMoveInFlight.current = false;
      }
    },
    [providers, setProviders, refreshProviders, showToast],
  );

  return { updateProviderPriority, moveProviderPriority };
}
