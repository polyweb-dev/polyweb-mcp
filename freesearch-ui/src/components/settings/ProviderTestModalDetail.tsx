import React from "react"

export const ModalDetail: React.FC<{ label: string; value: string; mono?: boolean }> = ({
  label,
  value,
  mono = false,
}) => (
  <>
    <dt className="text-[var(--muted)]">{label}</dt>
    <dd className={`min-w-0 break-words text-[var(--text-strong)] ${mono ? "font-mono text-[12px]" : ""}`}>
      {value}
    </dd>
  </>
)
