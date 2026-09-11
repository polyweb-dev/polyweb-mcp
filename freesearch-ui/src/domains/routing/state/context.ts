import { createContext } from "react";
import type { BackendRoutingConfig } from "@/domains/routing/api/wire";
import type { FallbackConfig, RoutingPreset } from "@/domains/routing/model/types";

export interface RoutingValue {
  fallbackConfig: FallbackConfig;
  routingLoading: boolean;
  routingError: string | null;
  routingPreset: RoutingPreset;
  costOptimizationPreset: BackendRoutingConfig["cost_optimization_preset"];
  setRoutingPreset: (preset: RoutingPreset) => void;
  updateFallbackConfig: (partial: Partial<FallbackConfig>) => Promise<void>;
  updateCostPreset: (preset: BackendRoutingConfig["cost_optimization_preset"]) => Promise<void>;
  refreshRouting: () => Promise<void>;
}

export const RoutingContext = createContext<RoutingValue | undefined>(undefined);
