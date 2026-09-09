import React from "react"

const HEALTH_CONFIG: Record<
  string,
  { label: string; dotClass: string; textClass: string; bgClass: string }
> = {
  healthy: {
    label: "Healthy",
    dotClass: "bg-[#22c55e]",
    textClass: "text-[#22c55e]",
    bgClass: "bg-[#22c55e]/15",
  },
  offline: {
    label: "Offline",
    dotClass: "bg-[#eab308]",
    textClass: "text-[#eab308]",
    bgClass: "bg-[#eab308]/15",
  },
  degraded: {
    label: "Degraded",
    dotClass: "bg-[#f59e0b]",
    textClass: "text-[#f59e0b]",
    bgClass: "bg-[#f59e0b]/15",
  },
  rate_limited: {
    label: "Rate limited",
    dotClass: "bg-[#f97316]",
    textClass: "text-[#f97316]",
    bgClass: "bg-[#f97316]/15",
  },
  circuit_broken: {
    label: "Circuit broken",
    dotClass: "bg-[#ef4444]",
    textClass: "text-[#ef4444]",
    bgClass: "bg-[#ef4444]/15",
  },
  open: {
    label: "Open",
    dotClass: "bg-[#ef4444]",
    textClass: "text-[#ef4444]",
    bgClass: "bg-[#ef4444]/15",
  },
}

export const HealthStatus: React.FC<{ status: string }> = ({ status }) => {
  const config = HEALTH_CONFIG[status] ?? {
    label: status.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
    dotClass: "bg-[var(--muted)]",
    textClass: "text-[var(--muted)]",
    bgClass: "bg-white/[0.06]",
  }

  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-[12px] font-medium ${config.bgClass} ${config.textClass}`}
    >
      <span aria-hidden="true" className={`size-2 rounded-full ${config.dotClass}`} />
      <span>{config.label}</span>
    </span>
  )
}
