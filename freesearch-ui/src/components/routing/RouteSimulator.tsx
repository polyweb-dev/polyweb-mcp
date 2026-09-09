import React, { useState } from "react"
import { Search } from "lucide-react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { ComposerShell } from "@/components/common/ComposerShell"
import { SegmentedControl } from "@/components/common/SegmentedControl"
import { getEligibleProviders } from "./routingUtils"
import { ExecutionPipeline } from "./simulator/ExecutionPipeline"

type SimulatorOperation = "Search" | "Fetch"

const SIMULATOR_OPERATIONS: readonly SimulatorOperation[] = ["Search", "Fetch"]

/**
 * Route simulator: resolves a hypothetical request through the current
 * strategy and renders the ingress → primary → fallback pipeline.
 */
export const RouteSimulator: React.FC = () => {
  const { providers, fallbackConfig, routingPreset } = useFreeSearch()
  const [operation, setOperation] = useState<SimulatorOperation>("Search")
  // Operation captured when a run starts; a mid-run switch must not repaint the pipeline.
  const [submittedOp, setSubmittedOp] = useState<SimulatorOperation>("Search")
  const [requestInput, setRequestInput] = useState("")
  const [hasSimulated, setHasSimulated] = useState(false)

  const op: "search" | "fetch" = operation === "Fetch" ? "fetch" : "search"
  const eligible = getEligibleProviders(providers, op, routingPreset)

  // Failover depth = fallback hops beyond the primary, bounded by maxAttempts.
  const maxFallbacks = fallbackConfig.enabled ? fallbackConfig.maxAttempts : 0
  const runOp: "search" | "fetch" = submittedOp === "Fetch" ? "fetch" : "search"
  const runEligible = getEligibleProviders(providers, runOp, routingPreset)
  const runPrimary = runEligible[0] ?? null
  const runFallbacks = runEligible.slice(1, 1 + maxFallbacks)

  const handleOperationChange = (next: string) => {
    setOperation(next as SimulatorOperation)
    setHasSimulated(false)
  }

  const handleSimulate = () => {
    setSubmittedOp(operation)
    setHasSimulated(true)
  }

  return (
    <section className="flex flex-1 flex-col space-y-5 w-full max-w-none">
      <div
        data-testid="simulator-layout"
        data-state={hasSimulated ? "docked" : "hero"}
        className={`transition-all duration-300 ease-out motion-reduce:transition-none ${
          hasSimulated
            ? "top-docked"
            : "w-full mx-auto flex flex-1 min-h-[55vh] max-w-3xl flex-col justify-center"
        }`}
      >
        <ComposerShell
          testIdPrefix="simulator"
          inputRow={
            <div className="relative">
              <div
                className="absolute left-0 top-1/2 -translate-y-1/2 pl-1"
                style={{ color: "var(--muted)" }}
              >
                <Search className="size-5" />
              </div>
              <input
                type="text"
                value={requestInput}
                onChange={(e) => setRequestInput(e.target.value)}
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
                  onClick={handleSimulate}
                  className="inline-flex items-center gap-2 rounded-md px-5 py-2 text-[13px] font-medium text-white transition-opacity motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40"
                  style={{ background: "var(--signal)" }}
                >
                  <Search aria-hidden="true" className="size-3.5" />
                  Simulate route
                </button>
              </div>
            </div>
          }
          footer={
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
                onChange={handleOperationChange}
                ariaLabel="Simulator operation"
              />
            </div>
          }
        />
      </div>

      {eligible.length === 0 ? (
        <div className="p-2.5 rounded bg-[var(--surface)] border border-[var(--border-subtle)] text-[13px] text-[var(--muted)]">
          No eligible providers for this operation — enable global routing or a provider
          operation in settings.
        </div>
      ) : hasSimulated ? (
        <ExecutionPipeline
          operation={runOp}
          preset={routingPreset}
          primary={runPrimary}
          fallbacks={runFallbacks}
          failoverEnabled={fallbackConfig.enabled}
        />
      ) : null}
    </section>
  )
}

export { ExecutionPipeline } from "./simulator/ExecutionPipeline"
export { PipelineStep } from "./simulator/PipelineStep"
export { ProviderStep } from "./simulator/ProviderStep"
export { FallbackCascade } from "./simulator/FallbackCascade"
