import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react"
import type { BackendDashboard } from "@/services/api/backendTypes"
import { apiService } from "@/services/api/freesearchApi"
import { catalogNameOf } from "@/services/api/providerCatalog"
import { mapDashboardQuotas, mapDashboardUsage } from "@/services/api/mappers"
import type { DashboardQuota, UsageEvent, UsageTotal } from "@/types/freesearch"
import type { ToastNotification } from "./context"
import { errorMessage, usageTotalsFromDashboard } from "./providerMappers"

type ShowToast = (message: string, type?: ToastNotification["type"]) => void

type DashboardSetters = {
  setUsageEvents: Dispatch<SetStateAction<UsageEvent[]>>
  setUsageTotals: Dispatch<SetStateAction<UsageTotal[]>>
  setDashboardQuotas: Dispatch<SetStateAction<DashboardQuota[]>>
  setDashboardNotice: Dispatch<SetStateAction<string | null>>
  setUsageError: Dispatch<SetStateAction<string | null>>
  setUsageLoading: Dispatch<SetStateAction<boolean>>
}

type DashboardLoadOptions = DashboardSetters & {
  showToast: ShowToast
  isMounted?: () => boolean
}

function applyDashboard(
  dashboard: BackendDashboard,
  setters: DashboardSetters
): void {
  setters.setUsageEvents(mapDashboardUsage(dashboard, catalogNameOf))
  setters.setUsageTotals(usageTotalsFromDashboard(dashboard.usage_totals))
  setters.setDashboardQuotas(mapDashboardQuotas(dashboard))
  setters.setDashboardNotice(dashboard.notice)
}

async function loadDashboard({
  setUsageEvents,
  setUsageTotals,
  setDashboardQuotas,
  setDashboardNotice,
  setUsageError,
  setUsageLoading,
  showToast,
  isMounted = () => true,
}: DashboardLoadOptions): Promise<void> {
  try {
    const dashboard = await apiService.getDashboard()
    if (!isMounted()) return
    applyDashboard(dashboard, {
      setUsageEvents,
      setUsageTotals,
      setDashboardQuotas,
      setDashboardNotice,
      setUsageError,
      setUsageLoading,
    })
  } catch (error) {
    if (!isMounted()) return
    const message = errorMessage(error, "Unable to load usage telemetry")
    setUsageEvents([])
    setUsageTotals([])
    setDashboardQuotas([])
    setUsageError(message)
    showToast(message, "error")
  } finally {
    if (isMounted()) setUsageLoading(false)
  }
}

export function useDashboard({ showToast }: { showToast: ShowToast }) {
  const [usageEvents, setUsageEvents] = useState<UsageEvent[]>([])
  const [usageLoading, setUsageLoading] = useState(true)
  const [usageError, setUsageError] = useState<string | null>(null)
  const [usageTotals, setUsageTotals] = useState<UsageTotal[]>([])
  const [dashboardQuotas, setDashboardQuotas] = useState<DashboardQuota[]>([])
  const [dashboardNotice, setDashboardNotice] = useState<string | null>(null)

  const setters = useMemo(
    () => ({
      setUsageEvents,
      setUsageTotals,
      setDashboardQuotas,
      setDashboardNotice,
      setUsageError,
      setUsageLoading,
    }),
    []
  )
  const refreshDashboard = useCallback(async () => {
    setUsageLoading(true)
    setUsageError(null)
    await loadDashboard({ ...setters, showToast })
  }, [setters, showToast])

  useEffect(() => {
    let mounted = true
    void loadDashboard({ ...setters, showToast, isMounted: () => mounted })
    return () => {
      mounted = false
    }
  }, [setters, showToast])

  return useMemo(
    () => [
      {
        usageEvents,
        usageLoading,
        usageError,
        usageTotals,
        dashboardQuotas,
        quotaAvailable: dashboardQuotas.length > 0,
        dashboardNotice,
        refreshDashboard,
      },
      setUsageEvents,
    ] as const,
    [
      usageEvents,
      usageLoading,
      usageError,
      usageTotals,
      dashboardQuotas,
      dashboardNotice,
      refreshDashboard,
    ]
  )
}
