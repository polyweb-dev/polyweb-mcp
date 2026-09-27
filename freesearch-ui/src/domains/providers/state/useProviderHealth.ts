import { useCallback } from "react";
import { apiService } from "@/services/api/freesearchApi";
import { errorMessage } from "@/shared/api/http";
import type { CircuitBreakerStatus, ProviderConfig } from "@/domains/providers/model/types";
import { toBackendId, toUiId } from "@/domains/providers/api/idMapping";
import { mapBackendHealth } from "@/services/api/mappers";
import type { ShowToast } from "./context";

interface HealthDeps {
  providers: ProviderConfig[];
  setProviders: React.Dispatch<React.SetStateAction<ProviderConfig[]>>;
  showToast: ShowToast;
}

export function useProviderHealth({ providers, setProviders, showToast }: HealthDeps) {
  const setCircuitBreaker = useCallback(
    async (id: string, status: CircuitBreakerStatus) => {
      if (status === "open") {
        // GAP: 5 — the backend exposes reset only, so trips stay local to this session.
        setProviders((previous) =>
          previous.map((provider) =>
            provider.id === id
              ? { ...provider, circuitBreaker: "open", healthStatus: "circuit_broken" }
              : provider,
          ),
        );
        showToast(`Local trip for "${id}" — local trip — backend exposes reset only`, "warning");
        return;
      }

      if (status !== "closed") return;
      try {
        const reset = await apiService.resetCircuitBreaker(toBackendId(id));
        setProviders((previous) =>
          previous.map((provider) =>
            provider.id === toUiId(reset.provider)
              ? {
                  ...provider,
                  circuitBreaker: "closed",
                  healthStatus:
                    provider.healthStatus === "circuit_broken" ? "healthy" : provider.healthStatus,
                }
              : provider,
          ),
        );
      } catch (error) {
        showToast(errorMessage(error, "Unable to reset circuit breaker"), "error");
      }
    },
    [setProviders, showToast],
  );

  const testProviderConnection = useCallback(
    async (id: string) => {
      const provider = providers.find((candidate) => candidate.id === id);
      if (!provider) return { success: false, latencyMs: 0, message: "Provider not found" };

      try {
        const result = await apiService.testProvider(toBackendId(id));
        setProviders((previous) =>
          previous.map((candidate) =>
            candidate.id === id
              ? {
                  ...candidate,
                  latencyP95Ms: result.latency_ms,
                  healthStatus: mapBackendHealth(result.status, candidate.circuitBreaker),
                }
              : candidate,
          ),
        );
        const message = result.detail ?? result.status;
        showToast(
          result.ok ? `Test passed for ${provider.name}` : `Test failed for ${provider.name}: ${message}`,
          result.ok ? "success" : "error",
        );
        return { success: result.ok, latencyMs: result.latency_ms, message };
      } catch (error) {
        const message = errorMessage(error, "Provider test failed");
        setProviders((previous) =>
          previous.map((candidate) =>
            candidate.id === id
              ? {
                  ...candidate,
                  healthStatus: "offline",
                }
              : candidate,
          ),
        );
        showToast(`Test failed for ${provider.name}: ${message}`, "error");
        return { success: false, latencyMs: provider.latencyP95Ms ?? 0, message };
      }
    },
    [providers, setProviders, showToast],
  );

  return { setCircuitBreaker, testProviderConnection };
}
