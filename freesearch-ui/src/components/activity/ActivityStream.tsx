import React, { useState } from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { Modal } from "@/components/common/Modal"
import type { UsageEvent } from "@/types/freesearch"

export const ActivityStream: React.FC = () => {
  const { usageEvents, clearUsageEvents } = useFreeSearch()
  const [selectedEvent, setSelectedEvent] = useState<UsageEvent | null>(null)
  const [filterOp, setFilterOp] = useState<"all" | "search" | "fetch">("all")

  const filteredEvents = usageEvents.filter((evt) => {
    if (filterOp !== "all" && evt.operation !== filterOp) return false
    return true
  })

  return (
    <div className="space-y-8">
      {/* Page heading with filter and clear */}
      <div className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-4 pb-2 border-b border-[var(--border-subtle)]">
        <div>
          <h2 className="text-xl font-medium tracking-tight text-[var(--text-strong)]">Activity</h2>
          <p className="text-sm text-[var(--muted)] mt-0.5">
            Audit trail of aggregated queries, routing decisions, fallback traces, and latency telemetry.
          </p>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1 text-xs">
            {(["all", "search", "fetch"] as const).map((op) => (
              <button
                key={op}
                onClick={() => setFilterOp(op)}
                className="px-3 py-1 rounded capitalize font-medium transition-colors"
                style={{
                  background: filterOp === op ? "var(--signal-muted)" : "var(--elevated)",
                  color: filterOp === op ? "var(--signal)" : "var(--muted)",
                  border: `1px solid ${filterOp === op ? "var(--signal)" : "var(--border-subtle)"}`,
                }}
              >
                {op}
              </button>
            ))}
          </div>

          <button
            onClick={clearUsageEvents}
            className="text-xs text-[var(--muted)] hover:text-white transition-colors hover:underline"
          >
            Clear log
          </button>
        </div>
      </div>

      {/* Events Table / Stream */}
      {filteredEvents.length === 0 ? (
        <div className="p-12 text-center border border-[var(--border-subtle)] rounded-lg bg-[var(--elevated)]">
          <p className="text-xs text-[var(--muted)]">
            No events recorded yet. Run queries in the Playground to populate live activity traces.
          </p>
        </div>
      ) : (
        <div className="border border-[var(--border-subtle)] rounded-lg overflow-hidden">
          {/* Table Header */}
          <div
            className="grid items-center text-xs font-medium py-2.5 px-4 bg-[var(--elevated)] border-b border-[var(--border-subtle)] text-[var(--muted)]"
            style={{
              gridTemplateColumns: "100px 80px 160px 1fr 120px 90px 80px",
            }}
          >
            <span>Time</span>
            <span>Operation</span>
            <span>Provider</span>
            <span>Query / Destination</span>
            <span className="text-center">Status</span>
            <span className="text-right">Latency</span>
            <span className="text-right">Cost</span>
          </div>

          {/* Event Rows */}
          {filteredEvents.map((evt) => {
            const isFallback = evt.status === "fallback_recovered"

            return (
              <div
                key={evt.id}
                onClick={() => setSelectedEvent(evt)}
                className="grid items-center py-3 px-4 text-xs border-b last:border-b-0 border-[var(--border-subtle)] hover:bg-[var(--elevated)] transition-colors cursor-pointer"
                style={{
                  gridTemplateColumns: "100px 80px 160px 1fr 120px 90px 80px",
                }}
              >
                {/* Time */}
                <span className="font-mono text-[11px] text-[var(--muted)]">
                  {new Date(evt.timestamp).toLocaleTimeString()}
                </span>

                {/* Operation */}
                <span className="font-mono text-[11px] capitalize text-[var(--text)]">
                  {evt.operation}
                </span>

                {/* Provider */}
                <div className="flex items-center gap-1.5 min-w-0 pr-2">
                  <span className="font-medium text-[var(--text-strong)] truncate">
                    {evt.providerName}
                  </span>
                </div>

                {/* Query / URL */}
                <div className="min-w-0 pr-4">
                  <span className="font-mono text-[11px] text-[var(--muted)] truncate block">
                    {evt.queryOrUrl}
                  </span>
                </div>

                {/* Status */}
                <div className="flex items-center justify-center">
                  {isFallback ? (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 font-mono">
                      fallback
                    </span>
                  ) : (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 font-mono">
                      direct
                    </span>
                  )}
                </div>

                {/* Latency */}
                <span className="font-mono text-[11px] text-right text-[var(--text)]">
                  {evt.latencyMs}ms
                </span>

                {/* Cost */}
                <span className="font-mono text-[11px] text-right text-[var(--muted)]">
                  {evt.costCredits}cr
                </span>
              </div>
            )
          })}
        </div>
      )}

      {/* Trace detail modal */}
      {selectedEvent && (
        <Modal
          isOpen={!!selectedEvent}
          onClose={() => setSelectedEvent(null)}
          title={`${selectedEvent.operation} trace`}
          subtitle={`${selectedEvent.id} · ${selectedEvent.timestamp}`}
          maxWidth="lg"
        >
          <div className="space-y-4 text-xs">
            <div>
              <span className="text-[var(--muted)] block mb-1">Target query or URL</span>
              <p className="p-3 rounded bg-[var(--elevated)] font-mono text-[var(--signal)] break-all border border-[var(--border-subtle)]">
                {selectedEvent.queryOrUrl}
              </p>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="p-3 rounded bg-[var(--elevated)] border border-[var(--border-subtle)]">
                <span className="text-[var(--muted)] block mb-1">Resolved provider</span>
                <p className="font-medium text-[var(--text-strong)]">
                  {selectedEvent.providerName}
                  <span className="ml-2 font-mono text-[var(--muted)]">
                    ({selectedEvent.providerId})
                  </span>
                </p>
              </div>

              <div className="p-3 rounded bg-[var(--elevated)] border border-[var(--border-subtle)]">
                <span className="text-[var(--muted)] block mb-1">Roundtrip latency</span>
                <p className="font-mono text-[var(--text-strong)]">
                  {selectedEvent.latencyMs}ms
                </p>
              </div>
            </div>

            <div>
              <span className="text-[var(--muted)] block mb-1">Arbitration reason</span>
              <p className="p-3 rounded bg-[var(--elevated)] text-[var(--text)] border border-[var(--border-subtle)] leading-relaxed">
                {selectedEvent.routeReason}
              </p>
            </div>

            <div>
              <span className="text-[var(--muted)] block mb-1">Execution hop cascade</span>
              <p className="p-3 rounded bg-[var(--elevated)] font-mono text-[var(--text)] border border-[var(--border-subtle)]">
                {selectedEvent.fallbackChain.join(" → ")}
              </p>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
