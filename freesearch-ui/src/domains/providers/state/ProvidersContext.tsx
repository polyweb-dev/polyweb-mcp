import React, { useCallback, useRef, useState } from "react";
import { apiService } from "@/services/api/freesearchApi";
import { errorMessage } from "@/shared/api/http";
import type { ToastNotification } from "@/shared/notifications/context";
import { toBackendId, toUiId } from "@/domains/providers/api/idMapping";
import type { BackendSecretStatus } from "@/domains/providers/api/wire";
import type { CircuitBreakerStatus, ProviderConfig } from "@/domains/providers/model/types";
import {
  mapProviderRows,
  updateProviderFromWire,
  priorityPatchesForMove,
  type ProviderPriorityPatch,
} from "@/domains/providers/model/providerMapping";
import { mapBackendHealth } from "@/services/api/mappers";

export type ShowToast = (message: string, type?: ToastNotification["type"]) => void;
import { ProvidersContext } from "./context";

async function restoreProviderPriorities(completed: ProviderPriorityPatch[]): Promise<void> {
  for (const { provider } of [...completed].reverse()) {
    try {
      await apiService.patchProvider(toBackendId(provider.id), { priority: provider.priority });
    } catch {
      // The authoritative refresh remains the fallback if compensation fails.
    }
  }
}

export const ProvidersProvider: React.FC<{
  showToast: ShowToast;
  children: React.ReactNode;
}> = ({ showToast, children }) => {
  const [providers, setProviders] = useState<ProviderConfig[]>([]);
  const [providersLoading, setProvidersLoading] = useState(true);
  const [providersError, setProvidersError] = useState<string | null>(null);
  const priorityMoveInFlight = useRef(false);

  const refreshProviders = useCallback(async () => {
    setProvidersLoading(true);
    setProvidersError(null);
    try {
      const rows = await apiService.listProviders();
      setProviders(mapProviderRows(rows));
    } catch (error) {
      const message = errorMessage(error, "Unable to load providers");
      setProviders([]);
      setProvidersError(message);
      showToast(message, "error");
    } finally {
      setProvidersLoading(false);
    }
  }, [showToast]);

  const toggleProvider = useCallback(
    async (id: string, enabled: boolean): Promise<void> => {
      try {
        const wire = await apiService.patchProvider(toBackendId(id), { enabled });
        setProviders((previous) => updateProviderFromWire(previous, wire));
        showToast(`${enabled ? "Enabled" : "Disabled"} provider "${id}"`, "success");
      } catch (error) {
        showToast(errorMessage(error, "Unable to update provider"), "error");
      }
    },
    [showToast],
  );

  const toggleProviderSearch = useCallback((id: string, enabled: boolean) => {
    // GAP: 4 — the backend exposes global enable only; operation toggles are session-only.
    setProviders((previous) =>
      previous.map((provider) =>
        provider.id === id && provider.capabilities.includes("search")
          ? { ...provider, searchEnabled: enabled }
          : provider,
      ),
    );
  }, []);

  const toggleProviderFetch = useCallback((id: string, enabled: boolean) => {
    // GAP: 4 — the backend exposes global enable only; operation toggles are session-only.
    setProviders((previous) =>
      previous.map((provider) =>
        provider.id === id && provider.capabilities.includes("fetch")
          ? { ...provider, fetchEnabled: enabled }
          : provider,
      ),
    );
  }, []);

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
    [showToast],
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
    [providers, refreshProviders, showToast],
  );

  const setCircuitBreaker = useCallback(
    async (id: string, status: CircuitBreakerStatus) => {
      if (status === "open") {
        // GAP: 5 — the backend exposes reset only, so trips stay local to this session.
        setProviders((previous) =>
          previous.map((provider) =>
            provider.id === id
              ? { ...provider, circuitBreaker: "open", healthStatus: "circuit_broken" }
              : provider,
          ),
        );
        showToast(`Local trip for "${id}" — local trip — backend exposes reset only`, "warning");
        return;
      }

      if (status !== "closed") return;
      try {
        const reset = await apiService.resetCircuitBreaker(toBackendId(id));
        setProviders((previous) =>
          previous.map((provider) =>
            provider.id === toUiId(reset.provider)
              ? {
                  ...provider,
                  circuitBreaker: "closed",
                  healthStatus:
                    provider.healthStatus === "circuit_broken" ? "healthy" : provider.healthStatus,
                }
              : provider,
          ),
        );
      } catch (error) {
        showToast(errorMessage(error, "Unable to reset circuit breaker"), "error");
      }
    },
    [showToast],
  );

  const testProviderConnection = useCallback(
    async (id: string) => {
      const provider = providers.find((candidate) => candidate.id === id);
      if (!provider) return { success: false, latencyMs: 0, message: "Provider not found" };

      try {
        const result = await apiService.testProvider(toBackendId(id));
        setProviders((previous) =>
          previous.map((candidate) =>
            candidate.id === id
              ? {
                  ...candidate,
                  latencyP95Ms: result.latency_ms,
                  healthStatus: mapBackendHealth(result.status, candidate.circuitBreaker),
                }
              : candidate,
          ),
        );
        const message = result.detail ?? result.status;
        showToast(
          result.ok ? `Test passed for ${provider.name}` : `Test failed for ${provider.name}: ${message}`,
          result.ok ? "success" : "error",
        );
        return { success: result.ok, latencyMs: result.latency_ms, message };
      } catch (error) {
        const message = errorMessage(error, "Provider test failed");
        showToast(`Test failed for ${provider.name}: ${message}`, "error");
        return { success: false, latencyMs: provider.latencyP95Ms ?? 0, message };
      }
    },
    [providers, showToast],
  );

  const updateSecretRow = useCallback((id: string, secret: BackendSecretStatus) => {
    setProviders((previous) =>
      previous.map((provider) =>
        provider.id === id
          ? {
              ...provider,
              hasKey: secret.presence !== "missing",
              keyVaultStatus: secret.presence,
              keyMasked: secret.fingerprint ?? "—",
              keySource: secret.source,
            }
          : provider,
      ),
    );
  }, []);

  const saveProviderKey = useCallback(
    async (id: string, rawKey: string): Promise<boolean> => {
      const trimmed = rawKey.trim();
      if (!trimmed) return false;
      // GAP: 13 — environment and dotenv sources can shadow a vault write.
      try {
        const secret = await apiService.putSecret(toBackendId(id), trimmed);
        updateSecretRow(id, secret);
        if (secret.source === "environment" || secret.source === "dotenv") {
          showToast(`Stored key for "${id}" — env key shadows vault`, "warning");
        } else {
          showToast(`API key stored for "${id}"`, "success");
        }
        return true;
      } catch (error) {
        showToast(errorMessage(error, "Unable to store API key"), "error");
        return false;
      }
    },
    [showToast, updateSecretRow],
  );

  const deleteProviderKey = useCallback(
    async (id: string): Promise<boolean> => {
      try {
        const secret = await apiService.deleteSecret(toBackendId(id));
        updateSecretRow(id, secret);
        showToast(`API key deleted for "${id}"`, "success");
        return true;
      } catch (error) {
        showToast(errorMessage(error, "Unable to delete API key"), "error");
        return false;
      }
    },
    [showToast, updateSecretRow],
  );

  const value = React.useMemo(
    () => ({
      providers,
      providersLoading,
      providersError,
      refreshProviders,
      toggleProvider,
      toggleProviderSearch,
      toggleProviderFetch,
      updateProviderPriority,
      moveProviderPriority,
      setCircuitBreaker,
      testProviderConnection,
      saveProviderKey,
      deleteProviderKey,
    }),
    [
      providers,
      providersLoading,
      providersError,
      refreshProviders,
      toggleProvider,
      toggleProviderSearch,
      toggleProviderFetch,
      updateProviderPriority,
      moveProviderPriority,
      setCircuitBreaker,
      testProviderConnection,
      saveProviderKey,
      deleteProviderKey,
    ],
  );

  return <ProvidersContext.Provider value={value}>{children}</ProvidersContext.Provider>;
};

