import { useCallback, useEffect, useState } from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { toBackendId } from "@/services/api/mappers"
import { apiService } from "@/services/api/freesearchApi"
import type {
  BackendManualQuota,
  BackendManualQuotaPayload,
} from "@/domains/dashboard/api/manualQuotaWire"
import { formatManualRange, formatPercent1dp, remainingPercent1dp } from "./manualQuotaMath"

export interface ManualQuotaEstimate {
  percentText: string
  rangeText: string
  percent: number
}

export interface ManualQuotaOverlay {
  manual: BackendManualQuota | null
  estimate: ManualQuotaEstimate | null
  save: (payload: BackendManualQuotaPayload) => Promise<void>
  remove: () => Promise<void>
}

function toEstimate(manual: BackendManualQuota | null): ManualQuotaEstimate | null {
  if (!manual) return null
  const percent = remainingPercent1dp(manual.allowance, manual.current_usage)
  if (percent === null) return null
  return {
    percentText: formatPercent1dp(percent) + "% remaining",
    rangeText: "Manual Entry " + formatManualRange(manual.billing_start, manual.billing_end),
    percent,
  }
}

/**
 * Manual billing-entry overlay state for one provider row. Reads stay honest:
 * a missing entry (404) or a failed read leaves `manual` null so no
 * estimated line is invented. Saves refresh the dashboard and then resolve.
 */
export function useManualQuota(providerId: string, eligible: boolean): ManualQuotaOverlay {
  const { refreshDashboard } = useFreeSearch()
  const [manual, setManual] = useState<BackendManualQuota | null>(null)

  useEffect(() => {
    if (!eligible) return
    let cancelled = false
    apiService
      .getManualQuota(toBackendId(providerId))
      .then((entry) => {
        if (!cancelled) setManual(entry)
      })
      .catch(() => {
        // No invented overlay: a failed read leaves the row as-is.
      })
    return () => {
      cancelled = true
    }
  }, [eligible, providerId])

  const save = useCallback(
    async (payload: BackendManualQuotaPayload): Promise<void> => {
      const saved = await apiService.putManualQuota(toBackendId(providerId), payload)
      setManual(saved)
      await refreshDashboard()
    },
    [providerId, refreshDashboard]
  )

  const remove = useCallback(async (): Promise<void> => {
    await apiService.deleteManualQuota(toBackendId(providerId))
    setManual(null)
    await refreshDashboard()
  }, [providerId, refreshDashboard])

  return { manual, estimate: toEstimate(manual), save, remove }
}
