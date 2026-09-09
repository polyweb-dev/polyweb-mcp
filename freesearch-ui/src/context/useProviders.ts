import { useCallback, useEffect, useMemo, useState } from "react"
import { apiService } from "@/services/api/freesearchApi"
import type { ProviderConfig } from "@/types/freesearch"
import type { ToastNotification } from "./context"
import { errorMessage, mapProviderRows } from "./providerMappers"
import { useProviderActions } from "./useProviderActions"

type ShowToast = (message: string, type?: ToastNotification["type"]) => void

type UseProvidersOptions = {
  showToast: ShowToast
}

export function useProviders({ showToast }: UseProvidersOptions) {
  const [providers, setProviders] = useState<ProviderConfig[]>([])
  const [providersLoading, setProvidersLoading] = useState(true)
  const [providersError, setProvidersError] = useState<string | null>(null)

  const refreshProviders = useCallback(async () => {
    setProvidersLoading(true)
    setProvidersError(null)
    try {
      const rows = await apiService.listProviders()
      setProviders(mapProviderRows(rows))
    } catch (error) {
      const message = errorMessage(error, "Unable to load providers")
      setProviders([])
      setProvidersError(message)
      showToast(message, "error")
    } finally {
      setProvidersLoading(false)
    }
  }, [showToast])

  useEffect(() => {
    let mounted = true

    const loadProviders = async () => {
      try {
        const rows = await apiService.listProviders()
        if (mounted) setProviders(mapProviderRows(rows))
      } catch (error) {
        if (!mounted) return
        const message = errorMessage(error, "Unable to load providers")
        setProviders([])
        setProvidersError(message)
        showToast(message, "error")
      } finally {
        if (mounted) setProvidersLoading(false)
      }
    }

    void loadProviders()
    return () => {
      mounted = false
    }
  }, [showToast])

  const actions = useProviderActions({
    providers,
    setProviders,
    refreshProviders,
    showToast,
  })

  return useMemo(
    () => ({
      providers,
      providersLoading,
      providersError,
      refreshProviders,
      ...actions,
    }),
    [actions, providers, providersError, providersLoading, refreshProviders]
  )
}
