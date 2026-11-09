import { createContext } from "react";
import type { FallbackConfig } from "@/domains/routing/model/types";

export interface RoutingValue {
  fallbackConfig: FallbackConfig;
  routingLoading: boolean;
  routingError: string | null;
  /** Role capability flags from the composition. */
  canReadControls: boolean;
  canEditControls: boolean;
  updateFallbackConfig: (partial: Partial<FallbackConfig>) => Promise<void>;
  refreshRouting: () => Promise<void>;
}

export const RoutingContext = createContext<RoutingValue | undefined>(undefined);
