import React from "react"
import type { UsageEvent } from "@/types/freesearch"

function statusColor(status: UsageEvent["status"]): string {
  if (status === "success") return "var(--status-healthy)"
  if (status === "fallback_recovered") return "var(--status-warning)"
  return "var(--status-danger)"
}

export const StatusPill: React.FC<{ status: UsageEvent["status"] }> = ({ status }) => (
  <span
    className="text-[12px] px-1.5 py-0.5 rounded font-medium"
    style={{
      color: statusColor(status),
      background: "var(--elevated)",
      border: "1px solid var(--border-subtle)",
    }}
  >
    {status}
  </span>
)
