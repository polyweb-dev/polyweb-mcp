import {
  useCallback,
  useMemo,
  useRef,
  type Dispatch,
  type SetStateAction,
} from "react"
import { apiService } from "@/services/api/freesearchApi"
import { mapBackendHealth } from "@/services/api/mappers"
import { toBackendId, toUiId } from "@/services/api/mappers"
import type {
  CircuitBreakerStatus,
  ProviderConfig,
} from "@/types/freesearch"
import type { ToastNotification } from "./context"
import {
  compensatePriority,
  errorMessage,
  priorityPatchesForMove,
  updateProviderFromWire,
  updateSecretRow,
  type ProviderPriorityPatch,
} from "./providerMappers"

type SetProviders = Dispatch<SetStateAction<ProviderConfig[]>>
type ShowToast = (message: string, type?: ToastNotification["type"]) => void

type ProviderActionsOptions = {
  providers: ProviderConfig[]
  setProviders: SetProviders
  refreshProviders: () => Promise<void>
  showToast: ShowToast
}

type ProviderMutationOptions = {
  setProviders: SetProviders
  showToast: ShowToast
}

function createToggleProvider({
  setProviders,
  showToast,
}: ProviderMutationOptions) {
  return async (id: string, enabled: boolean): Promise<void> => {
    try {
      const wire = await apiService.patchProvider(toBackendId(id), { enabled })
      setProviders((previous) => updateProviderFromWire(previous, wire))
      showToast(`${enabled ? "Enabled" : "Disabled"} provider "${id}"`, "success")
    } catch (error) {
      showToast(errorMessage(error, "Unable to update provider"), "error")
    }
  }
}

function createToggleProviderSearch(setProviders: SetProviders) {
  return (id: string, enabled: boolean) => {
    // GAP: 4 — the backend exposes global enable only; operation toggles are session-only.
    setProviders((previous) =>
      previous.map((provider) =>
        provider.id === id && provider.capabilities.includes("search")
          ? { ...provider, searchEnabled: enabled }
          : provider
      )
    )
  }
}

function createToggleProviderFetch(setProviders: SetProviders) {
  return (id: string, enabled: boolean) => {
    // GAP: 4 — the backend exposes global enable only; operation toggles are session-only.
    setProviders((previous) =>
      previous.map((provider) =>
        provider.id === id && provider.capabilities.includes("fetch")
          ? { ...provider, fetchEnabled: enabled }
          : provider
      )
    )
  }
}

function createUpdateProviderPriority({
  setProviders,
  showToast,
}: ProviderMutationOptions) {
  return async (id: string, newPriority: number): Promise<boolean> => {
    try {
      const wire = await apiService.patchProvider(toBackendId(id), { priority: newPriority })
      setProviders((previous) => updateProviderFromWire(previous, wire))
      return true
    } catch (error) {
      showToast(errorMessage(error, "Unable to update provider priority"), "error")
      return false
    }
  }
}

async function compensateProviderPriorities(
  completedPatches: ProviderPriorityPatch[]
): Promise<void> {
  for (const { provider } of compensatePriority(completedPatches)) {
    try {
      await apiService.patchProvider(toBackendId(provider.id), {
        priority: provider.priority,
      })
    } catch {
      // The authoritative refresh remains the fallback if compensation fails.
    }
  }
}

function createSetCircuitBreaker({
  setProviders,
  showToast,
}: ProviderMutationOptions) {
  return async (id: string, status: CircuitBreakerStatus) => {
    if (status === "open") {
      // GAP: 5 — the backend exposes reset only, so trips stay local to this session.
      setProviders((previous) =>
        previous.map((provider) =>
          provider.id === id
            ? { ...provider, circuitBreaker: "open", healthStatus: "circuit_broken" }
            : provider
        )
      )
      showToast(`Local trip for "${id}" — local trip — backend exposes reset only`, "warning")
      return
    }

    if (status !== "closed") return
    try {
      const reset = await apiService.resetCircuitBreaker(toBackendId(id))
      setProviders((previous) =>
        previous.map((provider) =>
          provider.id === toUiId(reset.provider)
            ? {
                ...provider,
                circuitBreaker: "closed",
                healthStatus:
                  provider.healthStatus === "circuit_broken"
                    ? "healthy"
                    : provider.healthStatus,
              }
            : provider
        )
      )
    } catch (error) {
      showToast(errorMessage(error, "Unable to reset circuit breaker"), "error")
    }
  }
}

function createTestProviderConnection({
  providers,
  setProviders,
  showToast,
}: Omit<ProviderActionsOptions, "refreshProviders">) {
  return async (id: string) => {
    const provider = providers.find((candidate) => candidate.id === id)
    if (!provider) return { success: false, latencyMs: 0, message: "Provider not found" }

    try {
      const result = await apiService.testProvider(toBackendId(id))
      setProviders((previous) =>
        previous.map((candidate) =>
          candidate.id === id
            ? {
                ...candidate,
                latencyP95Ms: result.latency_ms,
                healthStatus: mapBackendHealth(result.status, candidate.circuitBreaker),
              }
            : candidate
        )
      )
      const message = result.detail ?? result.status
      showToast(
        result.ok ? `Test passed for ${provider.name}` : `Test failed for ${provider.name}: ${message}`,
        result.ok ? "success" : "error"
      )
      return { success: result.ok, latencyMs: result.latency_ms, message }
    } catch (error) {
      const message = errorMessage(error, "Provider test failed")
      showToast(`Test failed for ${provider.name}: ${message}`, "error")
      return { success: false, latencyMs: provider.latencyP95Ms ?? 0, message }
    }
  }
}

function createSaveProviderKey({
  setProviders,
  showToast,
}: ProviderMutationOptions) {
  return async (id: string, rawKey: string): Promise<boolean> => {
    const trimmed = rawKey.trim()
    if (!trimmed) return false
    // GAP: 13 — environment and dotenv sources can shadow a vault write.
    try {
      const secret = await apiService.putSecret(toBackendId(id), trimmed)
      setProviders((previous) => updateSecretRow(previous, id, secret))
      if (secret.source === "environment" || secret.source === "dotenv") {
        showToast(`Stored key for "${id}" — env key shadows vault`, "warning")
      } else {
        showToast(`API key stored for "${id}"`, "success")
      }
      return true
    } catch (error) {
      showToast(errorMessage(error, "Unable to store API key"), "error")
      return false
    }
  }
}

function createDeleteProviderKey({
  setProviders,
  showToast,
}: ProviderMutationOptions) {
  return async (id: string): Promise<boolean> => {
    try {
      const secret = await apiService.deleteSecret(toBackendId(id))
      setProviders((previous) => updateSecretRow(previous, id, secret))
      showToast(`API key deleted for "${id}"`, "success")
      return true
    } catch (error) {
      showToast(errorMessage(error, "Unable to delete API key"), "error")
      return false
    }
  }
}

export function useProviderActions(options: ProviderActionsOptions) {
  const { providers, setProviders, refreshProviders, showToast } = options
  const priorityMoveInFlight = useRef(false)

  const toggleProvider = useMemo(
    () => createToggleProvider({ setProviders, showToast }),
    [setProviders, showToast]
  )
  const toggleProviderSearch = useMemo(
    () => createToggleProviderSearch(setProviders),
    [setProviders]
  )
  const toggleProviderFetch = useMemo(
    () => createToggleProviderFetch(setProviders),
    [setProviders]
  )
  const updateProviderPriority = useMemo(
    () => createUpdateProviderPriority({ setProviders, showToast }),
    [setProviders, showToast]
  )
  const moveProviderPriority = useCallback(
    async (id: string, direction: "up" | "down") => {
      if (priorityMoveInFlight.current) return

      const sorted = [...providers].sort((a, b) => a.priority - b.priority)
      const index = sorted.findIndex((provider) => provider.id === id)
      const targetIndex = direction === "up" ? index - 1 : index + 1
      if (index < 0 || targetIndex < 0 || targetIndex >= sorted.length) return

      const patches = priorityPatchesForMove(sorted, index, targetIndex)
      const completed: ProviderPriorityPatch[] = []
      priorityMoveInFlight.current = true

      try {
        for (const patch of patches) {
          const wire = await apiService.patchProvider(toBackendId(patch.provider.id), {
            priority: patch.priority,
          })
          completed.push(patch)
          setProviders((previous) => updateProviderFromWire(previous, wire))
        }
        await refreshProviders()
      } catch (error) {
        await compensateProviderPriorities(completed)
        await refreshProviders()
        showToast(errorMessage(error, "Unable to move provider priority"), "error")
      } finally {
        priorityMoveInFlight.current = false
      }
    },
    [providers, refreshProviders, setProviders, showToast]
  )
  const setCircuitBreaker = useMemo(
    () => createSetCircuitBreaker({ setProviders, showToast }),
    [setProviders, showToast]
  )
  const testProviderConnection = useMemo(
    () => createTestProviderConnection({ providers, setProviders, showToast }),
    [providers, setProviders, showToast]
  )
  const saveProviderKey = useMemo(
    () => createSaveProviderKey({ setProviders, showToast }),
    [setProviders, showToast]
  )
  const deleteProviderKey = useMemo(
    () => createDeleteProviderKey({ setProviders, showToast }),
    [setProviders, showToast]
  )

  return useMemo(
    () => ({
      toggleProvider,
      toggleProviderSearch,
      toggleProviderFetch,
      updateProviderPriority,
      moveProviderPriority,
      setCircuitBreaker,
      testProviderConnection,
      saveProviderKey,
      deleteProviderKey,
    }),
    [
      toggleProvider,
      toggleProviderSearch,
      toggleProviderFetch,
      updateProviderPriority,
      moveProviderPriority,
      setCircuitBreaker,
      testProviderConnection,
      saveProviderKey,
      deleteProviderKey,
    ]
  )
}
