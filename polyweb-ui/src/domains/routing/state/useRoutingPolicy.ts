import { useCallback } from "react";
import { apiService } from "@/services/api/polywebApi";
import { errorMessage } from "@/shared/api/http";
import type { ToastNotification } from "@/shared/notifications/context";
import type { FallbackConfig } from "@/domains/routing/model/types";
import { mapRoutingConfig } from "@/services/api/mappers";

type ShowToast = (message: string, type?: ToastNotification["type"]) => void;

interface RoutingPolicyDeps {
  showToast: ShowToast;
  /** False for a role without control-edit access: local state only. */
  canEditControls: boolean;
  fallbackConfig: FallbackConfig;
  setFallbackConfig: React.Dispatch<React.SetStateAction<FallbackConfig>>;
}

/**
 * Write side of the routing policy.
 *
 * A role without control-edit access keeps every control functional as a local
 * simulation, and no backend write starts from this hook.
 */
export function useRoutingPolicy({
  showToast,
  canEditControls,
  fallbackConfig,
  setFallbackConfig,
}: RoutingPolicyDeps) {
  const updateFallbackConfig = useCallback(
    async (partial: Partial<FallbackConfig>) => {
      setFallbackConfig((previous) => ({ ...previous, ...partial }));
      if (!canEditControls) return;

      const hasBackendFields = partial.enabled !== undefined || partial.maxAttempts !== undefined;
      if (!hasBackendFields) {
        // GAP: 10 — backend does not expose per-condition or timeout-budget controls.
        return;
      }

      const nextEnabled = partial.enabled ?? fallbackConfig.enabled;
      const nextMaxAttempts = partial.maxAttempts ?? fallbackConfig.maxAttempts;
      try {
        const wire = await apiService.updateRoutingConfig({
          fallback_policy: nextEnabled ? "chained" : "first_only",
          max_attempts: nextMaxAttempts,
        });
        const mapped = mapRoutingConfig(wire);
        setFallbackConfig((previous) => ({ ...previous, ...mapped, ...partial }));
      } catch (error) {
        showToast(errorMessage(error, "Unable to update fallback configuration"), "error");
        try {
          const authoritative = await apiService.getRoutingConfig();
          setFallbackConfig((previous) => ({ ...previous, ...mapRoutingConfig(authoritative) }));
        } catch {
          // Keep the error toast when the authoritative read is unavailable.
        }
      }
    },
    [
      canEditControls,
      fallbackConfig.enabled,
      fallbackConfig.maxAttempts,
      setFallbackConfig,
      showToast,
    ]
  );

  return { updateFallbackConfig };
}
