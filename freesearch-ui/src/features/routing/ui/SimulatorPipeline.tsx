import { useFreeSearch } from "@/context/useFreeSearch"
import { getProviderReason } from "@/domains/routing"
import type { ProviderConfig } from "@/types/freesearch"
import { FallbackCascade } from "./FallbackCascade"
import { PipelineStep } from "./PipelineStep"
import { ProviderStep } from "./ProviderStep"

export interface SimulatorPipelineProps {
  operation: "search" | "fetch"
  preset: ReturnType<typeof useFreeSearch>["routingPreset"]
  primary: ProviderConfig | null
  fallbacks: ProviderConfig[]
  failoverEnabled: boolean
}

/**
 * Execution pipeline: ingress, primary, and the failover cascade. Output
 * matches the monolith step for step; only the ownership moved.
 */
export function SimulatorPipeline({
  operation,
  preset,
  primary,
  fallbacks,
  failoverEnabled,
}: SimulatorPipelineProps) {
  return (
    <div className="p-4 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] space-y-4">
      <PipelineStep
        index="0"
        title="Client Ingress"
        detail={"Incoming " + operation + " request"}
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
