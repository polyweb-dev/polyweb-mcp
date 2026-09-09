import React, { useMemo } from "react"
import type { FreeSearchContextType } from "./context"
import { FreeSearchContext } from "./context"
import { useDashboard } from "./useDashboard"
import { useProviders } from "./useProviders"
import { useRoutingConfig } from "./useRoutingConfig"
import { useSearchRunner } from "./useSearchRunner"
import { useToasts } from "./useToasts"

function composeContextValue(
  providerState: ReturnType<typeof useProviders>,
  routingState: ReturnType<typeof useRoutingConfig>,
  dashboardState: ReturnType<typeof useDashboard>[0],
  runnerState: ReturnType<typeof useSearchRunner>,
  toastState: ReturnType<typeof useToasts>
): FreeSearchContextType {
  return {
    ...providerState,
    ...routingState,
    ...dashboardState,
    ...runnerState,
    ...toastState,
  }
}

export const FreeSearchProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const toastState = useToasts()
  const providerState = useProviders({ showToast: toastState.showToast })
  const routingState = useRoutingConfig({ showToast: toastState.showToast })
  const [dashboardState, setUsageEvents] = useDashboard({
    showToast: toastState.showToast,
  })
  const runnerState = useSearchRunner({
    fallbackEnabled: routingState.fallbackConfig.enabled,
    refreshDashboard: dashboardState.refreshDashboard,
    showToast: toastState.showToast,
    setUsageEvents,
  })
  const value = useMemo(
    () => composeContextValue(providerState, routingState, dashboardState, runnerState, toastState),
    [providerState, routingState, dashboardState, runnerState, toastState]
  )

  return <FreeSearchContext.Provider value={value}>{children}</FreeSearchContext.Provider>
}
