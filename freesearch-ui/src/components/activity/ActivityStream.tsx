import React, { useState } from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { ProviderLogo } from "@/components/common/ProviderLogo"
import { ActivityHeader, type OperationFilter } from "./ActivityHeader"
import { StatusPill } from "./StatusPill"
import { TraceDetailModal } from "./TraceDetailModal"
import { unitLabel } from "@/services/api/mappers"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/shared/ui/table"
import type { UsageEvent } from "@/types/freesearch"

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
      <ActivityHeader
        filterOp={filterOp}
        onFilterChange={(value) => setFilterOp(value.toLowerCase() as OperationFilter)}
      />

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
                  <TableCell className="px-4 py-2.5 text-right text-[var(--muted)] tnum">
                    {evt.costCredits} {activityUnitLabel(evt)}
                  </TableCell>
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

function activityUnitLabel(event: UsageEvent): string {
  if (event.unitKind === null) {
    return event.id.endsWith("-local") ? "pending" : "legacy (mixed)"
  }
  return event.displayUnit ?? unitLabel(event.unitKind, event.displayUnit)
}
