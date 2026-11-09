import React from "react"
import { X } from "lucide-react"

export interface ToastItem {
  id: string
  message: string
  type: "success" | "info" | "warning" | "error"
}

export interface ToastContainerProps {
  toasts: ToastItem[]
  onDismiss: (id: string) => void
}

/**
 * Business-independent toast stack. Toast state stays with the owning
 * provider; this primitive only renders the stack and reports dismissals.
 */
export const ToastContainer: React.FC<ToastContainerProps> = ({
  toasts,
  onDismiss,
}) => {
  if (toasts.length === 0) return null

  const accentMap = {
    success: "var(--status-healthy)",
    warning: "var(--status-warning)",
    error: "var(--status-danger)",
    info: "var(--signal)",
  }

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm pointer-events-none">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className="pointer-events-auto flex items-center gap-3 px-4 py-3 rounded-md animate-in slide-in-from-bottom-3 duration-200"
          style={{
            background: "var(--elevated)",
            border: "1px solid var(--border-subtle)",
            borderLeft: `3px solid ${accentMap[toast.type]}`,
          }}
        >
          <p className="text-[13px] flex-1" style={{ color: "var(--text-strong)" }}>
            {toast.message}
          </p>
          <button
            onClick={() => onDismiss(toast.id)}
            className="p-0.5 rounded transition-colors"
            style={{ color: "var(--muted)" }}
            aria-label="Dismiss"
          >
            <X className="size-3.5" />
          </button>
        </div>
      ))}
    </div>
  )
}
