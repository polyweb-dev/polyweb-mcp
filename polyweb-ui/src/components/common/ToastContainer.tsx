import React from "react"
import { usePolyweb } from "@/context/usePolyweb"
import { ToastContainer as ToastContainerView } from "@/shared/ui/ToastContainer"

/**
 * Context-bound toast stack. Rendering lives in the shared presentational
 * primitive; this wrapper only supplies live toast state and dismissal.
 */
export const ToastContainer: React.FC = () => {
  const { toasts, dismissToast } = usePolyweb()

  return <ToastContainerView toasts={toasts} onDismiss={dismissToast} />
}
