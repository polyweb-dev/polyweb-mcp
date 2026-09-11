import React from "react"
import { Modal } from "@/shared/ui/Modal"
import { ProviderLogo } from "@/components/common/ProviderLogo"
import type { UsageEvent } from "@/types/freesearch"

export const TraceDetailModal: React.FC<{ event: UsageEvent; onClose: () => void }> = ({
  event,
  onClose,
}) => (
  <Modal isOpen onClose={onClose} title={`${event.operation} trace`} subtitle={event.timestamp}>
    <div className="space-y-4 text-[13px]">
      <div className="grid grid-cols-2 gap-4">
        <div className="p-3 rounded bg-[var(--elevated)] border border-[var(--border-subtle)]">
          <span className="text-[var(--muted)] block mb-1">Resolved provider</span>
          <div className="flex items-center gap-2">
            <ProviderLogo providerId={event.providerId} name={event.providerName} />
            <p className="font-medium text-[var(--text-strong)]">{event.providerName}</p>
          </div>
        </div>

        <div className="p-3 rounded bg-[var(--elevated)] border border-[var(--border-subtle)]">
          <span className="text-[var(--muted)] block mb-1">Roundtrip latency</span>
          <p className="text-[var(--text-strong)] tnum">
            {event.latencyMs === null ? "—" : `${event.latencyMs}ms`}
          </p>
        </div>
      </div>

      <div>
        <span className="text-[var(--muted)] block mb-1">Arbitration reason</span>
        <p className="p-3 rounded bg-[var(--elevated)] text-[var(--text)] border border-[var(--border-subtle)] leading-relaxed">
          {event.routeReason}
        </p>
      </div>

      <div>
        <span className="text-[var(--muted)] block mb-1">Execution hop cascade</span>
        <p className="p-3 rounded bg-[var(--elevated)] text-[var(--text)] border border-[var(--border-subtle)] tnum">
          {event.fallbackChain.join(" → ")}
        </p>
      </div>
    </div>
  </Modal>
)
