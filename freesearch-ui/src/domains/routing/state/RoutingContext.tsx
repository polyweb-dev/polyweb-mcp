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
import { useRoutingPolicy } from "./useRoutingPolicy";

export const RoutingProvider: React.FC<{
  showToast: ShowToast;
  canReadControls: boolean;
  canEditControls: boolean;
  children: React.ReactNode;
}> = ({ showToast, canReadControls, canEditControls, children }) => {
  const [fallbackConfig, setFallbackConfig] = useState<FallbackConfig>(INITIAL_FALLBACK_CONFIG);
  const [routingLoading, setRoutingLoading] = useState(true);
  const [routingError, setRoutingError] = useState<string | null>(null);
  const [routingPreset, setRoutingPreset] = useState<RoutingPreset>("priority");
  const [costOptimizationPreset, setCostOptimizationPreset] = useState<
    BackendRoutingConfig["cost_optimization_preset"]
  >(DEFAULT_COST_PRESET);

  const refreshRouting = useCallback(async () => {
    if (!canReadControls) {
      // A role without control-read access keeps the local defaults and a clear
      // busy flag. The client never manufactures a routing policy.
      setRoutingError(null);
      setRoutingLoading(false);
      return;
    }
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
  }, [canReadControls, showToast]);

  const { updateFallbackConfig, updateCostPreset } = useRoutingPolicy({
    showToast,
    canEditControls,
    fallbackConfig,
    costOptimizationPreset,
    setFallbackConfig,
    setCostOptimizationPreset,
  });
  const value = React.useMemo(
    () => ({
      fallbackConfig,
      routingLoading,
      routingError,
      routingPreset,
      costOptimizationPreset,
      canReadControls,
      canEditControls,
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
      canReadControls,
      canEditControls,
      updateFallbackConfig,
      updateCostPreset,
      refreshRouting,
    ],
  );

  return <RoutingContext.Provider value={value}>{children}</RoutingContext.Provider>;
};
