import { createContext } from "react";
import type { ToastNotification } from "@/shared/notifications/context";
import type { CircuitBreakerStatus, ProviderConfig } from "@/domains/providers/model/types";

export type ShowToast = (message: string, type?: ToastNotification["type"]) => void;

export interface ProvidersValue {
  providers: ProviderConfig[];
  providersLoading: boolean;
  providersError: string | null;
  /** Role capability flags from the composition. */
  canReadControls: boolean;
  canEditControls: boolean;
  refreshProviders: () => Promise<void>;
  toggleProvider: (id: string, enabled: boolean) => Promise<void>;
  toggleProviderSearch: (id: string, enabled: boolean) => Promise<void>;
  toggleProviderFetch: (id: string, enabled: boolean) => Promise<void>;
  updateProviderPriority: (id: string, newPriority: number) => Promise<boolean>;
  moveProviderPriority: (id: string, direction: "up" | "down") => Promise<void>;
  reorderProviderPriority: (sourceId: string, targetId: string) => Promise<void>;
  setCircuitBreaker: (id: string, status: CircuitBreakerStatus) => Promise<void>;
  testProviderConnection: (id: string) => Promise<{
    success: boolean;
    latencyMs: number;
    message: string;
  }>;
  saveProviderKey: (id: string, rawKey: string) => Promise<boolean>;
  deleteProviderKey: (id: string) => Promise<boolean>;
}

export const ProvidersContext = createContext<ProvidersValue | undefined>(undefined);
