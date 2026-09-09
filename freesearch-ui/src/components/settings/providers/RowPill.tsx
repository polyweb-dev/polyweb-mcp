import React from "react"

export const RowPill: React.FC<{ tone: "signal" | "healthy"; children: React.ReactNode }> = ({ tone, children }) => (
  <span
    className="whitespace-nowrap rounded px-1.5 py-0.5 text-[12px]"
    style={{
      background: tone === "signal" ? "var(--signal-muted)" : "rgba(34, 197, 94, 0.1)",
      color: tone === "signal" ? "var(--signal)" : "var(--status-healthy)",
    }}
  >
    {children}
  </span>
)
