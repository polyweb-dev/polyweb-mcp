import React, { useCallback, useState } from "react";
import { apiService } from "@/services/api/freesearchApi";
import { errorMessage } from "@/shared/api/http";
import type { ToastNotification } from "@/shared/notifications/context";
import type { BackendRoutingConfig } from "@/domains/routing/api/wire";
import type { FallbackConfig, RoutingPreset } from "@/domains/routing/model/types";
import { mapRoutingConfig } from "@/services/api/mappers";

export type ShowToast = (message: string, type?: ToastNotification["type"]) => void;

const INITIAL_FALLBACK_CONFIG: FallbackConfig = {
  enabled: true,
  maxAttempts: 3,
  fallbackOnRateLimit: true,
  fallbackOnTimeout: true,
  fallbackOnServerError: true,
};

const DEFAULT_COST_PRESET: BackendRoutingConfig["cost_optimization_preset"] = "balanced";

import { RoutingContext } from "./context";

export const RoutingProvider: React.FC<{
  showToast: ShowToast;
  children: React.ReactNode;
}> = ({ showToast, children }) => {
  const [fallbackConfig, setFallbackConfig] = useState<FallbackConfig>(INITIAL_FALLBACK_CONFIG);
  const [routingLoading, setRoutingLoading] = useState(true);
  const [routingError, setRoutingError] = useState<string | null>(null);
  const [routingPreset, setRoutingPreset] = useState<RoutingPreset>("priority");
  const [costOptimizationPreset, setCostOptimizationPreset] = useState<
    BackendRoutingConfig["cost_optimization_preset"]
  >(DEFAULT_COST_PRESET);

  const refreshRouting = useCallback(async () => {
    setRoutingLoading(true);
    setRoutingError(null);
    try {
      const wire = await apiService.getRoutingConfig();
      setFallbackConfig((previous) => ({ ...previous, ...mapRoutingConfig(wire) }));
      setCostOptimizationPreset(wire.cost_optimization_preset);
    } catch (error) {
      const message = errorMessage(error, "Unable to load routing configuration");
      setRoutingError(message);
      showToast(message, "error");
    } finally {
      setRoutingLoading(false);
    }
  }, [showToast]);

  const updateFallbackConfig = useCallback(
    async (partial: Partial<FallbackConfig>) => {
      const hasBackendFields = partial.enabled !== undefined || partial.maxAttempts !== undefined;
      setFallbackConfig((previous) => ({ ...previous, ...partial }));
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
    [costOptimizationPreset, fallbackConfig.enabled, fallbackConfig.maxAttempts, showToast],
  );

  const updateCostPreset = useCallback(
    async (preset: BackendRoutingConfig["cost_optimization_preset"]): Promise<void> => {
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
    [fallbackConfig.enabled, fallbackConfig.maxAttempts, showToast],
  );

  const value = React.useMemo(
    () => ({
      fallbackConfig,
      routingLoading,
      routingError,
      routingPreset,
      costOptimizationPreset,
      setRoutingPreset,
      updateFallbackConfig,
      updateCostPreset,
      refreshRouting,
    }),
    [
      fallbackConfig,
      routingLoading,
      routingError,
      routingPreset,
      costOptimizationPreset,
      updateFallbackConfig,
      updateCostPreset,
      refreshRouting,
    ],
  );

  return <RoutingContext.Provider value={value}>{children}</RoutingContext.Provider>;
};
