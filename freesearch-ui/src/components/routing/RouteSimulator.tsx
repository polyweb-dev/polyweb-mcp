import React, { useState } from "react"
import { Search } from "lucide-react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { ComposerShell } from "@/components/common/ComposerShell"
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
        {highlight && (
          <span className="text-[12px] px-1.5 py-0.5 rounded bg-[var(--signal-muted)] text-[var(--signal)] font-medium">
            Primary
          </span>
        )}
        <span className="text-[13px] text-[var(--text)] tnum">
          {provider.latencyP95Ms === null ? "—" : `${provider.latencyP95Ms} ms`} p95
        </span>
      </div>
      <div className="flex items-center justify-between gap-2 mt-0.5 text-[13px] text-[var(--muted)]">
        <span>{reason}</span>
        <span className="tnum shrink-0">
          Quota {provider.quota.used ?? "—"}/{provider.quota.limit ?? "∞"}
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
          <span>{fallback.latencyP95Ms === null ? "—" : `${fallback.latencyP95Ms}ms`}</span>
          <span>
            {fallback.quota.used ?? "—"}/{fallback.quota.limit ?? "∞"}
          </span>
          <span className="hidden sm:inline">{getProviderReason(fallback, idx + 1, preset)}</span>
        </div>
      </div>
    ))}
  </div>
)
