import { useCallback } from "react";
import { apiService } from "@/services/api/freesearchApi";
import { errorMessage } from "@/shared/api/http";
import type { ProviderConfig } from "@/domains/providers/model/types";
import { toBackendId } from "@/domains/providers/api/idMapping";
import { mapProviderRows, updateProviderFromWire } from "@/domains/providers/model/providerMapping";
import type { ShowToast } from "./context";

interface StatusDeps {
  setProviders: React.Dispatch<React.SetStateAction<ProviderConfig[]>>;
  setProvidersLoading: React.Dispatch<React.SetStateAction<boolean>>;
  setProvidersError: React.Dispatch<React.SetStateAction<string | null>>;
  showToast: ShowToast;
  /** False for a role without control-read access: no request, empty state. */
  canReadControls: boolean;
}

export const OPERATION_TOGGLES_STORAGE_KEY = "freesearch:operation_toggles";

export interface StoredOperationToggle {
  searchEnabled?: boolean;
  fetchEnabled?: boolean;
}

export type StoredTogglesMap = Record<string, StoredOperationToggle>;

export function loadOperationToggles(): StoredTogglesMap {
  if (typeof window === "undefined" || !window.localStorage) return {};
  try {
    const raw = window.localStorage.getItem(OPERATION_TOGGLES_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as StoredTogglesMap) : {};
  } catch {
    return {};
  }
}

export function saveOperationToggle(id: string, update: Partial<StoredOperationToggle>): void {
  if (typeof window === "undefined" || !window.localStorage) return;
  try {
    const current = loadOperationToggles();
    current[id] = { ...current[id], ...update };
    window.localStorage.setItem(OPERATION_TOGGLES_STORAGE_KEY, JSON.stringify(current));
  } catch {
    // Ignore storage quota or security errors
  }
}

export function useProviderStatus({
  setProviders,
  setProvidersLoading,
  setProvidersError,
  showToast,
  canReadControls,
}: StatusDeps) {
  const refreshProviders = useCallback(async () => {
    if (!canReadControls) {
      // A role without control-read access keeps an empty catalog and a clear
      // busy flag. The client never manufactures provider health or presence.
      setProviders([]);
      setProvidersError(null);
      setProvidersLoading(false);
      return;
    }
    setProvidersLoading(true);
    setProvidersError(null);
    try {
      const rows = await apiService.listProviders();
      const mapped = mapProviderRows(rows);
      const savedToggles = loadOperationToggles();
      const hydrated = mapped.map((provider) => {
        const saved = savedToggles[provider.id];
        if (!saved) return provider;
        return {
          ...provider,
          ...(typeof saved.searchEnabled === "boolean" && provider.capabilities.includes("search")
            ? { searchEnabled: saved.searchEnabled }
            : {}),
          ...(typeof saved.fetchEnabled === "boolean" && provider.capabilities.includes("fetch")
            ? { fetchEnabled: saved.fetchEnabled }
            : {}),
        };
      });
      setProviders(hydrated);
    } catch (error) {
      const message = errorMessage(error, "Unable to load providers");
      setProviders([]);
      setProvidersError(message);
      showToast(message, "error");
    } finally {
      setProvidersLoading(false);
    }
  }, [canReadControls, setProviders, setProvidersLoading, setProvidersError, showToast]);

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
    [setProviders, showToast],
  );

  const toggleProviderSearch = useCallback(
    (id: string, enabled: boolean) => {
      saveOperationToggle(id, { searchEnabled: enabled });
      setProviders((previous) =>
        previous.map((provider) =>
          provider.id === id && provider.capabilities.includes("search")
            ? { ...provider, searchEnabled: enabled }
            : provider,
        ),
      );
    },
    [setProviders],
  );

  const toggleProviderFetch = useCallback(
    (id: string, enabled: boolean) => {
      saveOperationToggle(id, { fetchEnabled: enabled });
      setProviders((previous) =>
        previous.map((provider) =>
          provider.id === id && provider.capabilities.includes("fetch")
            ? { ...provider, fetchEnabled: enabled }
            : provider,
        ),
      );
    },
    [setProviders],
  );

  return { refreshProviders, toggleProvider, toggleProviderSearch, toggleProviderFetch };
}

