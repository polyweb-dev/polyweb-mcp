import React, { useState } from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { Modal } from "@/components/common/Modal"
import { ProviderLogo } from "@/components/common/ProviderLogo"
import { SegmentedControl } from "@/components/common/SegmentedControl"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { UsageEvent } from "@/types/freesearch"

type OperationFilter = "all" | "search" | "fetch"

const FILTER_OPTIONS = ["All", "Search", "Fetch"] as const

/**
 * Operational activity telemetry. Request targets (queries and URLs) are never
 * rendered — only provider, latency, routing reason, and hop metadata.
 */
export const ActivityStream: React.FC = () => {
  const { usageEvents, usageLoading, usageError } = useFreeSearch()
  const [selectedEvent, setSelectedEvent] = useState<UsageEvent | null>(null)
  const [filterOp, setFilterOp] = useState<OperationFilter>("all")

  const filteredEvents = usageEvents.filter(
    (evt) => filterOp === "all" || evt.operation === filterOp
  )

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-4 pb-2 border-b border-[var(--border-subtle)]">
        <div>
          <h2 className="text-[var(--text-strong)]">Activity</h2>
          <p className="text-[13px] text-[var(--muted)] mt-0.5">
            Operational telemetry for routing decisions, failover traces, and latency.
          </p>
        </div>

        <SegmentedControl
          options={FILTER_OPTIONS}
          value={filterOp[0].toUpperCase() + filterOp.slice(1)}
          onChange={(value) =>
            setFilterOp(value.toLowerCase() as OperationFilter)
          }
          ariaLabel="Activity operation filter"
        />
      </div>

      {usageLoading ? (
        <>
          <p className="p-12 text-center text-[13px] text-[var(--muted)]" role="status">
            Loading activity telemetry...
          </p>
          <div className="border border-[var(--border-subtle)] rounded-lg overflow-hidden" aria-busy="true">
            <Table className="text-[13px]">
              <TableHeader>
                <TableRow className="bg-[var(--elevated)] border-b border-[var(--border-subtle)]">
                  <TableHead className="h-9 px-4 text-[12px] text-[var(--muted)]">Time</TableHead>
                  <TableHead className="h-9 px-4 text-[12px] text-[var(--muted)]">Operation</TableHead>
                  <TableHead className="h-9 px-4 text-[12px] text-[var(--muted)]">Provider</TableHead>
                  <TableHead className="h-9 px-4 text-[12px] text-[var(--muted)] text-center">Status</TableHead>
                  <TableHead className="h-9 px-4 text-[12px] text-[var(--muted)] text-right">Latency</TableHead>
                  <TableHead className="h-9 px-4 text-[12px] text-[var(--muted)] text-right">Units</TableHead>
                </TableRow>
              </TableHeader>
            </Table>
          </div>
        </>
      ) : usageError ? (
        <p className="p-8 text-center border border-[var(--border-subtle)] rounded-lg bg-[var(--elevated)] text-[13px]" style={{ color: "var(--status-danger)" }}>
          Activity telemetry error: {usageError}
        </p>
      ) : filteredEvents.length === 0 ? (
        <div className="p-12 text-center border border-[var(--border-subtle)] rounded-lg bg-[var(--elevated)]">
          <p className="text-[13px] text-[var(--muted)]">
            No events recorded yet. Run a request in the Playground to populate live telemetry.
          </p>
        </div>
      ) : (
        <div className="border border-[var(--border-subtle)] rounded-lg overflow-hidden">
          <Table className="text-[13px]">
            <TableHeader>
              <TableRow className="bg-[var(--elevated)] hover:bg-[var(--elevated)] border-b border-[var(--border-subtle)]">
                <TableHead className="h-9 px-4 text-[12px] text-[var(--muted)]">Time</TableHead>
                <TableHead className="h-9 px-4 text-[12px] text-[var(--muted)]">Operation</TableHead>
                <TableHead className="h-9 px-4 text-[12px] text-[var(--muted)]">Provider</TableHead>
                <TableHead className="h-9 px-4 text-[12px] text-[var(--muted)] text-center">Status</TableHead>
                <TableHead className="h-9 px-4 text-[12px] text-[var(--muted)] text-right">Latency</TableHead>
                <TableHead className="h-9 px-4 text-[12px] text-[var(--muted)] text-right">Units</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredEvents.map((evt) => (
                <TableRow
                  key={evt.id}
                  onClick={() => setSelectedEvent(evt)}
                  className="cursor-pointer border-b border-[var(--border-subtle)] last:border-b-0"
                >
                  <TableCell className="px-4 py-2.5 text-[var(--muted)] tnum">
                    {new Date(evt.timestamp).toLocaleTimeString()}
                  </TableCell>
                  <TableCell className="px-4 py-2.5 capitalize text-[var(--text)]">{evt.operation}</TableCell>
                  <TableCell className="px-4 py-2.5">
                    <div className="flex items-center gap-2">
                      <ProviderLogo providerId={evt.providerId} name={evt.providerName} />
                      <span className="font-medium text-[var(--text-strong)]">{evt.providerName}</span>
                    </div>
                  </TableCell>
                  <TableCell className="px-4 py-2.5 text-center"><StatusPill status={evt.status} /></TableCell>
                  <TableCell className="px-4 py-2.5 text-right text-[var(--text)] tnum">
                    {evt.latencyMs === null ? "—" : `${evt.latencyMs}ms`}
                  </TableCell>
                  <TableCell className="px-4 py-2.5 text-right text-[var(--muted)] tnum">{evt.costCredits} units</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {selectedEvent && <TraceDetailModal event={selectedEvent} onClose={() => setSelectedEvent(null)} />}
    </div>
  )
}

function statusColor(status: UsageEvent["status"]): string {
  if (status === "success") return "var(--status-healthy)"
  if (status === "fallback_recovered") return "var(--status-warning)"
  return "var(--status-danger)"
}

const StatusPill: React.FC<{ status: UsageEvent["status"] }> = ({ status }) => (
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

const TraceDetailModal: React.FC<{ event: UsageEvent; onClose: () => void }> = ({
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
