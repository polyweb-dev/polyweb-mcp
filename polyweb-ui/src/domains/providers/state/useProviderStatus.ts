import { useCallback } from "react";
import { apiService } from "@/services/api/polywebApi";
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
      setProviders(mapProviderRows(rows));
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
    async (id: string, enabled: boolean): Promise<void> => {
      try {
        const wire = await apiService.patchProvider(toBackendId(id), { search_enabled: enabled });
        setProviders((previous) => updateProviderFromWire(previous, wire));
      } catch (error) {
        showToast(errorMessage(error, "Unable to update provider"), "error");
      }
    },
    [setProviders, showToast],
  );

  const toggleProviderFetch = useCallback(
    async (id: string, enabled: boolean): Promise<void> => {
      try {
        const wire = await apiService.patchProvider(toBackendId(id), { fetch_enabled: enabled });
        setProviders((previous) => updateProviderFromWire(previous, wire));
      } catch (error) {
        showToast(errorMessage(error, "Unable to update provider"), "error");
      }
    },
    [setProviders, showToast],
  );

  return { refreshProviders, toggleProvider, toggleProviderSearch, toggleProviderFetch };
}
