import { SegmentedControl } from "@/shared/ui/SegmentedControl"
import { SIMULATOR_OPERATIONS, type SimulatorOperation } from "../model/useSimulatorController"

export interface SimulatorFooterProps {
  operation: SimulatorOperation
  onOperationChange: (next: string) => void
}

/** Simulator footer: description plus the operation toggle. */
export function SimulatorFooter({ operation, onOperationChange }: SimulatorFooterProps) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        <h3 className="sr-only">Route simulator</h3>
        <span className="text-[13px] text-[var(--muted)]">
          Resolves a hypothetical request through the active strategy.
        </span>
      </div>
      <SegmentedControl
        options={SIMULATOR_OPERATIONS}
        value={operation}
        onChange={onOperationChange}
        ariaLabel="Simulator operation"
      />
    </div>
  )
}
