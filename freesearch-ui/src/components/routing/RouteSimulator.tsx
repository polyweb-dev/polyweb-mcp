import React, { useEffect, useRef, useState } from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { SegmentedControl } from "@/components/common/SegmentedControl"
import type { ProviderConfig } from "@/types/freesearch"
import { getEligibleProviders, getProviderReason } from "./routingUtils"

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
  const [isSimulating, setIsSimulating] = useState(false)
  const [hasSimulated, setHasSimulated] = useState(false)
  const resolveTimer = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (resolveTimer.current !== null) window.clearTimeout(resolveTimer.current)
    }
  }, [])

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
    setIsSimulating(true)
    setHasSimulated(false)
    resolveTimer.current = window.setTimeout(() => {
      setIsSimulating(false)
      setHasSimulated(true)
    }, 250)
  }

  return (
    <section className="space-y-5 max-w-3xl">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h3 className="text-[var(--text-strong)]">Route simulator</h3>
          <p className="text-[13px] text-[var(--muted)] mt-0.5">
            Resolves a hypothetical request through the active strategy.
          </p>
        </div>
        <SegmentedControl
          options={SIMULATOR_OPERATIONS}
          value={operation}
          onChange={handleOperationChange}
          ariaLabel="Simulator operation"
          disabled={isSimulating}
        />
      </div>

      <div className="flex items-center gap-2">
        <input
          type="text"
          value={requestInput}
          onChange={(e) => setRequestInput(e.target.value)}
          placeholder={
            operation === "Search" ? "Type simulated query..." : "Type simulated URL..."
          }
          className="flex-1 rounded-md border border-[var(--border-subtle)] bg-[var(--surface)] px-3 py-2 text-[13px] text-[var(--text)] font-mono placeholder:text-[var(--muted)] outline-none focus:border-[var(--signal)]"
        />
        <button
          type="button"
          onClick={handleSimulate}
          disabled={isSimulating}
          className="px-4 py-2 text-[13px] font-medium rounded-md text-white transition-opacity shrink-0 disabled:opacity-70 motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40"
          style={{ background: "var(--signal)" }}
        >
          {isSimulating ? "Resolving..." : "Simulate route"}
        </button>
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

interface ExecutionPipelineProps {
  operation: "search" | "fetch"
  preset: ReturnType<typeof useFreeSearch>["routingPreset"]
  primary: ProviderConfig | null
  fallbacks: ProviderConfig[]
  failoverEnabled: boolean
}

const ExecutionPipeline: React.FC<ExecutionPipelineProps> = ({
  operation,
  preset,
  primary,
  fallbacks,
  failoverEnabled,
}) => {
  return (
    <div className="p-4 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] space-y-4">
      <PipelineStep
        index="0"
        title="Client Ingress"
        detail={`Incoming ${operation} request`}
      />

      {primary && (
        <ProviderStep
          index="1"
          provider={primary}
          reason={getProviderReason(primary, 0, preset)}
          highlight
        />
      )}

      {failoverEnabled && fallbacks.length > 0 && (
        <FallbackCascade fallbacks={fallbacks} preset={preset} />
      )}

      {!failoverEnabled && (
        <div className="p-2.5 rounded bg-[var(--surface)] border border-[var(--border-subtle)] text-[13px] text-[var(--muted)]">
          <span className="font-medium text-[var(--text)]">Single-shot mode active</span>
          <span className="ml-1.5">Fallback cascade is disabled in settings.</span>
        </div>
      )}
    </div>
  )
}

const PipelineStep: React.FC<{ index: string; title: string; detail: string }> = ({
  index,
  title,
  detail,
}) => (
  <div className="flex items-start gap-3">
    <span className="mt-0.5 w-6 h-6 rounded-full bg-[var(--signal-muted)] border border-[var(--signal)]/40 flex items-center justify-center shrink-0 text-[12px] font-medium text-[var(--signal)] tnum">
      {index}
    </span>
    <div className="flex-1 min-w-0">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[13px] font-medium text-[var(--text-strong)]">{title}</span>
        <span className="text-[13px] text-[var(--muted)]">{detail}</span>
      </div>
    </div>
  </div>
)

const ProviderStep: React.FC<{
  index: string
  provider: ProviderConfig
  reason: string
  highlight?: boolean
}> = ({ index, provider, reason, highlight }) => (
  <div
    className={`flex items-start gap-3 p-3 rounded-md border transition-all ${
      highlight
        ? "bg-[var(--surface)] border-[var(--signal)]/40"
        : "bg-[var(--surface)] border-[var(--border-subtle)]"
    }`}
  >
    <span className="mt-0.5 w-6 h-6 rounded-full bg-[var(--signal-muted)] border border-[var(--signal)]/40 flex items-center justify-center shrink-0 text-[12px] font-medium text-[var(--signal)] tnum">
      {index}
    </span>
    <div className="flex-1 min-w-0">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[13px] font-semibold text-[var(--text-strong)]">
          {provider.name}
        </span>
        <span className="text-[13px] text-[var(--text)] tnum">{provider.latencyP95Ms} ms p95</span>
      </div>
      <div className="flex items-center justify-between gap-2 mt-0.5 text-[13px] text-[var(--muted)]">
        <span>{reason}</span>
        <span className="tnum shrink-0">
          Quota {provider.quota.used}/{provider.quota.limit ?? "∞"}
        </span>
      </div>
    </div>
  </div>
)

const FallbackCascade: React.FC<{
  fallbacks: ProviderConfig[]
  preset: ReturnType<typeof useFreeSearch>["routingPreset"]
}> = ({ fallbacks, preset }) => (
  <div className="space-y-2">
    <div className="flex items-center justify-between text-[13px] text-[var(--muted)]">
      <span className="font-medium text-[var(--text)]">Failover cascade</span>
      <span className="tnum">{fallbacks.length} fallbacks ready</span>
    </div>

    {fallbacks.map((fallback, idx) => (
      <div
        key={fallback.id}
        className="flex items-center justify-between p-2.5 rounded bg-[var(--surface)] border border-[var(--border-subtle)]"
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <span className="text-[12px] text-[var(--muted)] tnum">#{idx + 2}</span>
          <span className="text-[13px] font-medium text-[var(--text)] truncate">
            {fallback.name}
          </span>
          <span className="text-[12px] text-[var(--muted)]">
            {fallback.capabilities.includes("keyless_tier") ? "Keyless free tier" : `P${fallback.priority}`}
          </span>
        </div>
        <div className="flex items-center gap-3 text-[12px] text-[var(--muted)] tnum shrink-0">
          <span>{fallback.latencyP95Ms}ms</span>
          <span>
            {fallback.quota.used}/{fallback.quota.limit ?? "∞"}
          </span>
          <span className="hidden sm:inline">{getProviderReason(fallback, idx + 1, preset)}</span>
        </div>
      </div>
    ))}
  </div>
)
