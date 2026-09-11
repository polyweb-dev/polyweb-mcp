import { useState } from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { getEligibleProviders } from "@/domains/routing"
import type { ProviderConfig } from "@/types/freesearch"

export type SimulatorOperation = "Search" | "Fetch"

export const SIMULATOR_OPERATIONS: readonly SimulatorOperation[] = ["Search", "Fetch"]

export interface SimulatorController {
  operation: SimulatorOperation
  requestInput: string
  hasSimulated: boolean
  eligible: ProviderConfig[]
  runOp: "search" | "fetch"
  runPrimary: ProviderConfig | null
  runFallbacks: ProviderConfig[]
  failoverEnabled: boolean
  routingPreset: ReturnType<typeof useFreeSearch>["routingPreset"]
  setRequestInput: (value: string) => void
  handleOperationChange: (next: string) => void
  handleSimulate: () => void
}

/**
 * Route simulator state: the edited operation versus the operation captured
 * when a run starts (a mid-run switch must not repaint the pipeline).
 * Failover depth is bounded by maxAttempts beyond the primary.
 */
export function useSimulatorController(): SimulatorController {
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

  return {
    operation,
    requestInput,
    hasSimulated,
    eligible,
    runOp,
    runPrimary,
    runFallbacks,
    failoverEnabled: fallbackConfig.enabled,
    routingPreset,
    setRequestInput,
    handleOperationChange,
    handleSimulate,
  }
}
