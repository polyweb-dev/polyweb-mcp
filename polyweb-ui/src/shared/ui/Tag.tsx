import type { ReactNode } from "react"
import { cn } from "cn"

export type TagTone = "neutral" | "success" | "warning" | "danger" | "accent"

const TONES: Record<TagTone, string> = {
  neutral: "border-[var(--border-subtle)] text-[var(--muted)]",
  success: "border-[color-mix(in_srgb,var(--status-healthy)_35%,transparent)] text-[var(--status-healthy)]",
  warning: "border-[color-mix(in_srgb,var(--status-warning)_35%,transparent)] text-[var(--status-warning)]",
  danger: "border-[color-mix(in_srgb,var(--status-danger)_35%,transparent)] text-[var(--status-danger)]",
  accent: "border-[color-mix(in_srgb,var(--signal)_45%,transparent)] text-[var(--signal-ink)]",
}

export interface TagProps {
  children: ReactNode
  tone?: TagTone
  title?: string
  className?: string
}

/**
 * The one small label: quiet hairline outline, 11px text, no fill. Use it for
 * a short state or attribute next to a name (Keyless, Default, Archived), not
 * for counts or long text.
 */
export function Tag({ children, tone = "neutral", title, className }: TagProps) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex h-5 shrink-0 items-center rounded-[4px] border px-1.5 text-[11px] leading-none font-medium whitespace-nowrap",
        TONES[tone],
        className
      )}
    >
      {children}
    </span>
  )
}
