import { useCallback, useMemo, useState } from "react"
import type { ToastNotification } from "./context"

let toastSequence = 0

export function useToasts() {
  const [toasts, setToasts] = useState<ToastNotification[]>([])

  const showToast = useCallback(
    (message: string, type: ToastNotification["type"] = "info") => {
      toastSequence += 1
      const id = `toast-${toastSequence}`
      setToasts((previous) => [...previous, { id, message, type }])
      setTimeout(() => {
        if (typeof window !== "undefined") {
          setToasts((previous) => previous.filter((toast) => toast.id !== id))
        }
      }, 4500)
    },
    []
  )

  const dismissToast = useCallback((id: string) => {
    setToasts((previous) => previous.filter((toast) => toast.id !== id))
  }, [])

  return useMemo(
    () => ({ toasts, showToast, dismissToast }),
    [toasts, showToast, dismissToast]
  )
}
