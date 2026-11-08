import type { ReactNode } from "react"
import { ProviderLogo } from "@/shared/ui/ProviderLogo"
import { Tag } from "@/shared/ui/Tag"

interface ProviderCardHeaderProps {
  providerId: string
  providerName: string
  titleId: string
  free: boolean
  statement: string | null
  recordedAt: string | undefined
  info: ReactNode
  onActionsTarget: (target: HTMLDivElement | null) => void
  children: ReactNode
}

export function ProviderCardHeader({ providerId, providerName, titleId, free, statement, recordedAt, info, onActionsTarget, children }: ProviderCardHeaderProps) {
  return (
    <div className="flex min-h-12 min-w-0 items-start justify-between gap-3">
      <div className="flex min-w-0 items-center gap-3">
        <ProviderLogo providerId={providerId} name={providerName} className="size-8 rounded-full" />
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h4 id={titleId} className="truncate text-[15px] font-semibold text-[var(--text-strong)]">{providerName}</h4>
            {free && <Tag tone="neutral">Free tier</Tag>}
            {info}
          </div>
          {statement !== null && <p className="text-[12px] text-[var(--muted)]" title={recordedAt}>{statement}</p>}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <div ref={onActionsTarget} className="flex items-center gap-2" />
        {children}
      </div>
    </div>
  )
}
