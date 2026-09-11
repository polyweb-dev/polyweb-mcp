import { Search } from "lucide-react"
import type { SimulatorOperation } from "../model/useSimulatorController"

export interface SimulatorInputRowProps {
  value: string
  operation: SimulatorOperation
  onChange: (value: string) => void
  onSimulate: () => void
}

/** Simulator input row: icon, query/URL field, and the Simulate trigger. */
export function SimulatorInputRow({ value, operation, onChange, onSimulate }: SimulatorInputRowProps) {
  return (
    <div className="relative">
      <div
        className="absolute left-0 top-1/2 -translate-y-1/2 pl-1"
        style={{ color: "var(--muted)" }}
      >
        <Search className="size-5" />
      </div>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={
          operation === "Search"
            ? "Type simulated query..."
            : "Type simulated URL..."
        }
        className="w-full bg-transparent py-3 pl-9 pr-36 text-[15px] font-mono outline-none placeholder:text-[var(--muted)]"
        style={{ color: "var(--text-strong)" }}
      />
      <div className="absolute right-0 top-1/2 -translate-y-1/2">
        <button
          type="button"
          onClick={onSimulate}
          className="inline-flex items-center gap-2 rounded-md px-5 py-2 text-[13px] font-medium text-white transition-opacity motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40"
          style={{ background: "var(--signal)" }}
        >
          <Search aria-hidden="true" className="size-3.5" />
          Simulate route
        </button>
      </div>
    </div>
  )
}
