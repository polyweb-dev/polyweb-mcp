import { useCallback } from "react";
import { apiService } from "@/services/api/freesearchApi";
import { errorMessage } from "@/shared/api/http";
import type { ProviderConfig } from "@/domains/providers/model/types";
import { toBackendId } from "@/domains/providers/api/idMapping";
import type { BackendSecretStatus } from "@/domains/providers/api/wire";
import type { ShowToast } from "./context";

interface KeysDeps {
  setProviders: React.Dispatch<React.SetStateAction<ProviderConfig[]>>;
  showToast: ShowToast;
}

export function useProviderKeys({ setProviders, showToast }: KeysDeps) {
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
  }, [setProviders]);

  const saveProviderKey = useCallback(
    async (id: string, rawKey: string): Promise<boolean> => {
      const trimmed = rawKey.trim();
      if (!trimmed) return false;
      try {
        const secret = await apiService.putSecret(toBackendId(id), trimmed);
        updateSecretRow(id, secret);
        showToast("Key stored in the encrypted vault.", "success");
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

  return { saveProviderKey, deleteProviderKey };
}
