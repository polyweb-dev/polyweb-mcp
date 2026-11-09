import React from "react"
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/shared/ui/dialog"
import { cn } from "cn"
import { useDialogFocusTrap } from "./useDialogFocusTrap"

export interface ModalProps {
  isOpen: boolean
  onClose: () => void
  title?: React.ReactNode
  subtitle?: React.ReactNode
  children: React.ReactNode
  maxWidth?: "sm" | "md" | "lg" | "xl" | "2xl" | "4xl" | "6xl" | "7xl"
  /**
   * Opt-in fixed-height layout: the popup takes a fixed height, the header
   * stays put and the child owns its own scrolling. Default `false` lets the
   * popup grow with its content up to the viewport, then scrolls the body.
   */
  scrollBody?: boolean
}

const WIDTH_CLASSES: Record<NonNullable<ModalProps["maxWidth"]>, string> = {
  sm: "sm:max-w-sm",
  md: "sm:max-w-md",
  lg: "sm:max-w-lg",
  xl: "sm:max-w-xl",
  "2xl": "sm:max-w-2xl",
  "4xl": "sm:max-w-4xl",
  "6xl": "sm:max-w-6xl",
  "7xl": "sm:max-w-7xl",
}

/**
 * Title row of the dialog. The close button is rendered by the popup after the
 * body (so focus enters the content first) and positioned beside the title.
 */
function modalHeader(title: React.ReactNode, subtitle: React.ReactNode) {
  return (
    <div data-slot="modal-header" className="flex min-w-0 shrink-0 items-start pt-5 pr-14 pl-6">
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        {title && (
          <DialogTitle className="flex min-w-0 items-center gap-2 text-[15px] leading-6 font-medium text-[var(--text-strong)]">
            {title}
          </DialogTitle>
        )}
        {subtitle && (
          <DialogDescription className="text-[13px] leading-5 text-[var(--muted)]">
            {subtitle}
          </DialogDescription>
        )}
      </div>
    </div>
  )
}

/**
 * The one dialog surface of the application: a quiet title row with the close
 * button beside it, then the body. No divider separates them; spacing does.
 * The popup itself never clips, so a dropdown opened inside it can extend past
 * the body; the body scrolls when the content is taller than the viewport.
 */
export const Modal: React.FC<ModalProps> = ({
  isOpen,
  onClose,
  title,
  subtitle,
  children,
  maxWidth = "2xl",
  scrollBody = false,
}) => {
  const hasHeader = Boolean(title || subtitle)
  // F7: the dialog takes focus when it opens and keeps Tab inside it.
  const focusTrapRef = useDialogFocusTrap()

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        ref={focusTrapRef}
        showCloseButton
        className={cn(
          WIDTH_CLASSES[maxWidth],
          "flex min-w-0 flex-col gap-0 rounded-xl p-0",
          scrollBody ? "h-[min(90svh,920px)] max-h-[calc(100svh-2rem)]" : "max-h-[90svh]"
        )}
        style={{
          background: "var(--elevated)",
          border: "1px solid var(--border-subtle)",
          color: "var(--text)",
        }}
      >
        {hasHeader && modalHeader(title, subtitle)}
        <div
          data-slot="modal-body"
          className={cn(
            "min-h-0 min-w-0 flex-1 px-6 pb-6 text-[13px]",
            hasHeader ? "pt-5" : "pt-6",
            scrollBody ? "flex flex-col overflow-hidden" : "overflow-y-auto"
          )}
        >
          {children}
        </div>
      </DialogContent>
    </Dialog>
  )
}
