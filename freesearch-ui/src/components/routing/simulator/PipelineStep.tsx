import React from "react"

export const PipelineStep: React.FC<{ index: string; title: string; detail: string }> = ({
  index,
  title,
  detail,
}) => (
  <div className="flex items-start gap-3">
    <span className="mt-0.5 w-6 h-6 rounded-full bg-[var(--signal-muted)] border border-[var(--signal)]/40 flex items-center justify-center shrink-0 text-[12px] font-medium text-[var(--signal)] tnum">
      {index}
    </span>
    <div className="flex-1 min-w-0">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[13px] font-medium text-[var(--text-strong)]">{title}</span>
        <span className="text-[13px] text-[var(--muted)]">{detail}</span>
      </div>
    </div>
  </div>
)
