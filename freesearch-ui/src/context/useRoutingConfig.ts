import {
  useEffect,
  useMemo,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react"
import type { BackendRoutingConfig } from "@/services/api/backendTypes"
import { apiService } from "@/services/api/freesearchApi"
import { mapRoutingConfig } from "@/services/api/mappers"
import type { FallbackConfig, RoutingPreset } from "@/types/freesearch"
import type { ToastNotification } from "./context"
import { errorMessage } from "./providerMappers"

type ShowToast = (message: string, type?: ToastNotification["type"]) => void

type RoutingState = {
  fallbackEnabled: boolean
  maxAttempts: number
  costOptimizationPreset: BackendRoutingConfig["cost_optimization_preset"]
  setFallbackConfig: Dispatch<SetStateAction<FallbackConfig>>
  setCostOptimizationPreset: Dispatch<
    SetStateAction<BackendRoutingConfig["cost_optimization_preset"]>
  >
  showToast: ShowToast
}

function createUpdateFallbackConfig({
  fallbackEnabled,
  maxAttempts,
  costOptimizationPreset,
  setFallbackConfig,
  setCostOptimizationPreset,
  showToast,
}: RoutingState) {
  return async (partial: Partial<FallbackConfig>): Promise<void> => {
    const hasBackendFields = partial.enabled !== undefined || partial.maxAttempts !== undefined
    setFallbackConfig((previous) => ({ ...previous, ...partial }))
    if (!hasBackendFields) {
      // GAP: 10 — backend does not expose per-condition or timeout-budget controls.
      return
    }

    const nextEnabled = partial.enabled ?? fallbackEnabled
    const nextMaxAttempts = partial.maxAttempts ?? maxAttempts
    try {
      const wire = await apiService.updateRoutingConfig({
        fallback_policy: nextEnabled ? "chained" : "first_only",
        cost_optimization_preset: costOptimizationPreset,
        max_attempts: nextMaxAttempts,
      })
      const mapped = mapRoutingConfig(wire)
      setFallbackConfig((previous) => ({ ...previous, ...mapped, ...partial }))
      setCostOptimizationPreset(wire.cost_optimization_preset)
    } catch (error) {
      showToast(errorMessage(error, "Unable to update fallback configuration"), "error")
      try {
        const authoritative = await apiService.getRoutingConfig()
        setFallbackConfig((previous) => ({ ...previous, ...mapRoutingConfig(authoritative) }))
        setCostOptimizationPreset(authoritative.cost_optimization_preset)
      } catch {
        // Keep the error toast when the authoritative read is unavailable.
      }
    }
  }
}

function createUpdateCostPreset({
  fallbackEnabled,
  maxAttempts,
  setFallbackConfig,
  setCostOptimizationPreset,
  showToast,
}: Omit<RoutingState, "costOptimizationPreset">) {
  return async (
    preset: BackendRoutingConfig["cost_optimization_preset"]
  ): Promise<void> => {
    try {
      const wire = await apiService.updateRoutingConfig({
        fallback_policy: fallbackEnabled ? "chained" : "first_only",
        cost_optimization_preset: preset,
        max_attempts: maxAttempts,
      })
      setFallbackConfig((previous) => ({ ...previous, ...mapRoutingConfig(wire) }))
      setCostOptimizationPreset(wire.cost_optimization_preset)
    } catch (error) {
      showToast(errorMessage(error, "Unable to update cost optimization"), "error")
    }
  }
}

export function useRoutingConfig({ showToast }: { showToast: ShowToast }) {
  const [fallbackConfig, setFallbackConfig] = useState<FallbackConfig>({
    enabled: true,
    maxAttempts: 3,
    fallbackOnRateLimit: true,
    fallbackOnTimeout: true,
    fallbackOnServerError: true,
  })
  const [routingLoading, setRoutingLoading] = useState(true)
  const [routingError, setRoutingError] = useState<string | null>(null)
  const [routingPreset, setRoutingPreset] = useState<RoutingPreset>("priority")
  const [costOptimizationPreset, setCostOptimizationPreset] = useState<
    BackendRoutingConfig["cost_optimization_preset"]
  >("balanced")

  useEffect(() => {
    let mounted = true

    const loadRouting = async () => {
      try {
        const wire = await apiService.getRoutingConfig()
        if (!mounted) return
        setFallbackConfig((previous) => ({ ...previous, ...mapRoutingConfig(wire) }))
        setCostOptimizationPreset(wire.cost_optimization_preset)
      } catch (error) {
        if (!mounted) return
        const message = errorMessage(error, "Unable to load routing configuration")
        setRoutingError(message)
        showToast(message, "error")
      } finally {
        if (mounted) setRoutingLoading(false)
      }
    }

    void loadRouting()
    return () => {
      mounted = false
    }
  }, [showToast])

  const updateFallbackConfig = useMemo(
    () =>
      createUpdateFallbackConfig({
        fallbackEnabled: fallbackConfig.enabled,
        maxAttempts: fallbackConfig.maxAttempts,
        costOptimizationPreset,
        setFallbackConfig,
        setCostOptimizationPreset,
        showToast,
      }),
    [costOptimizationPreset, fallbackConfig.enabled, fallbackConfig.maxAttempts, showToast]
  )
  const updateCostPreset = useMemo(
    () =>
      createUpdateCostPreset({
        fallbackEnabled: fallbackConfig.enabled,
        maxAttempts: fallbackConfig.maxAttempts,
        setFallbackConfig,
        setCostOptimizationPreset,
        showToast,
      }),
    [fallbackConfig.enabled, fallbackConfig.maxAttempts, showToast]
  )

  return useMemo(
    () => ({
      fallbackConfig,
      routingLoading,
      routingError,
      routingPreset,
      costOptimizationPreset,
      setRoutingPreset,
      updateFallbackConfig,
      updateCostPreset,
    }),
    [
      fallbackConfig,
      routingLoading,
      routingError,
      routingPreset,
      costOptimizationPreset,
      updateFallbackConfig,
      updateCostPreset,
    ]
  )
}
