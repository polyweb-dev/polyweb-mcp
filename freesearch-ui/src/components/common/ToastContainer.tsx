import React from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { ToastContainer as ToastContainerView } from "@/shared/ui/ToastContainer"

/**
 * Context-bound toast stack. Rendering lives in the shared presentational
 * primitive; this wrapper only supplies live toast state and dismissal.
 */
export const ToastContainer: React.FC = () => {
  const { toasts, dismissToast } = useFreeSearch()

  return <ToastContainerView toasts={toasts} onDismiss={dismissToast} />
}
