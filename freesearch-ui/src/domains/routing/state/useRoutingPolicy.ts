import { useCallback } from "react";
import { apiService } from "@/services/api/freesearchApi";
import { errorMessage } from "@/shared/api/http";
import type { ToastNotification } from "@/shared/notifications/context";
import type { BackendRoutingConfig } from "@/domains/routing/api/wire";
import type { FallbackConfig } from "@/domains/routing/model/types";
import { mapRoutingConfig } from "@/services/api/mappers";

type ShowToast = (message: string, type?: ToastNotification["type"]) => void;

interface RoutingPolicyDeps {
  showToast: ShowToast;
  /** False for a role without control-edit access: local state only. */
  canEditControls: boolean;
  fallbackConfig: FallbackConfig;
  costOptimizationPreset: BackendRoutingConfig["cost_optimization_preset"];
  setFallbackConfig: React.Dispatch<React.SetStateAction<FallbackConfig>>;
  setCostOptimizationPreset: React.Dispatch<
    React.SetStateAction<BackendRoutingConfig["cost_optimization_preset"]>
  >;
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
  costOptimizationPreset,
  setFallbackConfig,
  setCostOptimizationPreset,
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
          cost_optimization_preset: costOptimizationPreset,
          max_attempts: nextMaxAttempts,
        });
        const mapped = mapRoutingConfig(wire);
        setFallbackConfig((previous) => ({ ...previous, ...mapped, ...partial }));
        setCostOptimizationPreset(wire.cost_optimization_preset);
      } catch (error) {
        showToast(errorMessage(error, "Unable to update fallback configuration"), "error");
        try {
          const authoritative = await apiService.getRoutingConfig();
          setFallbackConfig((previous) => ({ ...previous, ...mapRoutingConfig(authoritative) }));
          setCostOptimizationPreset(authoritative.cost_optimization_preset);
        } catch {
          // Keep the error toast when the authoritative read is unavailable.
        }
      }
    },
    [
      canEditControls,
      costOptimizationPreset,
      fallbackConfig.enabled,
      fallbackConfig.maxAttempts,
      setCostOptimizationPreset,
      setFallbackConfig,
      showToast,
    ]
  );

  const updateCostPreset = useCallback(
    async (preset: BackendRoutingConfig["cost_optimization_preset"]): Promise<void> => {
      setCostOptimizationPreset(preset);
      if (!canEditControls) return;
      try {
        const wire = await apiService.updateRoutingConfig({
          fallback_policy: fallbackConfig.enabled ? "chained" : "first_only",
          cost_optimization_preset: preset,
          max_attempts: fallbackConfig.maxAttempts,
        });
        setFallbackConfig((previous) => ({ ...previous, ...mapRoutingConfig(wire) }));
        setCostOptimizationPreset(wire.cost_optimization_preset);
      } catch (error) {
        showToast(errorMessage(error, "Unable to update cost optimization"), "error");
      }
    },
    [
      canEditControls,
      fallbackConfig.enabled,
      fallbackConfig.maxAttempts,
      setCostOptimizationPreset,
      setFallbackConfig,
      showToast,
    ]
  );

  return { updateFallbackConfig, updateCostPreset };
}
