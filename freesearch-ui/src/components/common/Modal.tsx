import React from "react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"
import { cn } from "@/lib/utils"

export interface ModalProps {
  isOpen: boolean
  onClose: () => void
  title?: string
  subtitle?: string
  children: React.ReactNode
  maxWidth?: "sm" | "md" | "lg" | "xl" | "2xl" | "4xl"
}

export const Modal: React.FC<ModalProps> = ({
  isOpen,
  onClose,
  title,
  subtitle,
  children,
  maxWidth = "2xl",
}) => {
  const widthClasses = {
    sm: "sm:max-w-sm",
    md: "sm:max-w-md",
    lg: "sm:max-w-lg",
    xl: "sm:max-w-xl",
    "2xl": "sm:max-w-2xl",
    "4xl": "sm:max-w-4xl",
  }

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        className={cn(
          "max-h-[90vh] overflow-y-auto p-6",
          widthClasses[maxWidth]
        )}
        style={{
          background: "var(--elevated)",
          border: "1px solid var(--border-subtle)",
          color: "var(--text)",
        }}
      >
        {(title || subtitle) && (
          <DialogHeader className="pb-4" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
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
        <div className="pt-4">{children}</div>
      </DialogContent>
    </Dialog>
  )
}
