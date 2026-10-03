import React from "react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/shared/ui/dialog"
import { cn } from "cn"
import { useDialogFocusTrap } from "./useDialogFocusTrap"

export interface ModalProps {
  isOpen: boolean
  onClose: () => void
  title?: string
  subtitle?: string
  children: React.ReactNode
  maxWidth?: "sm" | "md" | "lg" | "xl" | "2xl" | "4xl" | "6xl" | "7xl"
  /**
   * Opt-in fixed-header layout: the popup stops growing at the viewport, the
   * header and close button stay put, and only the body scrolls vertically.
   * Default `false` keeps the original single-scroller behavior for every
   * existing caller.
   */
  scrollBody?: boolean
}

export const Modal: React.FC<ModalProps> = ({
  isOpen,
  onClose,
  title,
  subtitle,
  children,
  maxWidth = "2xl",
  scrollBody = false,
}) => {
  const widthClasses = {
    sm: "sm:max-w-sm",
    md: "sm:max-w-md",
    lg: "sm:max-w-lg",
    xl: "sm:max-w-xl",
    "2xl": "sm:max-w-2xl",
    "4xl": "sm:max-w-4xl",
    "6xl": "sm:max-w-6xl",
    "7xl": "sm:max-w-7xl",
  }
  const hasHeader = Boolean(title || subtitle)
  // F7: the dialog takes focus when it opens and keeps Tab inside it.
  const focusTrapRef = useDialogFocusTrap()

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        ref={focusTrapRef}
        className={cn(
          widthClasses[maxWidth],
          scrollBody
            ? cn(
                "max-h-[calc(100svh-2rem)] min-w-0 overflow-hidden p-6",
                hasHeader ? "grid-rows-[auto_minmax(0,1fr)]" : "grid-rows-[minmax(0,1fr)]"
              )
            : "max-h-[90vh] overflow-y-auto p-6"
        )}
        style={{
          background: "var(--elevated)",
          border: "1px solid var(--border-subtle)",
          color: "var(--text)",
        }}
      >
        {hasHeader && (
          <DialogHeader
            className="min-w-0 shrink-0 pb-4"
            style={{ borderBottom: "1px solid var(--border-subtle)" }}
          >
            {title && (
              <DialogTitle className="text-[15px] font-medium" style={{ color: "var(--text-strong)" }}>
                {title}
              </DialogTitle>
            )}
            {subtitle && (
              <DialogDescription className="text-[13px] mt-0.5" style={{ color: "var(--muted)" }}>
                {subtitle}
              </DialogDescription>
            )}
          </DialogHeader>
        )}
        <div
          className={cn(
            "pt-4",
            scrollBody && "min-h-0 min-w-0 overflow-x-hidden overflow-y-auto overscroll-contain"
          )}
        >
          {children}
        </div>
      </DialogContent>
    </Dialog>
  )
}
