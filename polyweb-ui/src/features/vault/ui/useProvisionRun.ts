import { useState } from "react"
import type { VaultProject } from "@/domains/vault"
import { createKeyPool, createVaultKey } from "@/domains/vault"
import { ApiError } from "@/shared/api/http"
import {
  executeProvisionRun,
  judgeOutcomes,
  outcomeError,
  reconcileCreated,
} from "../model/bulkPools"
import type { BulkVaultRow, ProviderOutcome, ProvisionMode } from "../model/bulkPools"

const CLIENTS = { createKey: createVaultKey, createPool: createKeyPool }

/** Safe reason for a rejected write: fixed wording only, never the raw error,
 * whose detail may echo request content.
 */
function failureReason(error: unknown): string {
  return error instanceof ApiError && error.status === 409
    ? "conflicts with an existing pool or key — resolve it from the key row"
    : "did not save — try again"
}

/** Replace one provider's outcome line, or append it when it is new. */
function withOutcome(outcomes: readonly ProviderOutcome[], outcome: ProviderOutcome): ProviderOutcome[] {
  const known = outcomes.some((entry) => entry.providerType === outcome.providerType)
  return known
    ? outcomes.map((entry) => (entry.providerType === outcome.providerType ? outcome : entry))
    : [...outcomes, outcome]
}

/**
 * State of one pool-provisioning dialog run, shared by the bulk and the
 * keyless-defaults dialogs. A failing provider is blocked by name and the
 * rest still run; outcome lines and created records survive, so a retry
 * skips providers already created or assigned and reuses created keys, and
 * every write happens once. Only a clean success calls `onSaved` by itself;
 * otherwise the outcomes stay visible until `dismiss`, which reloads the page
 * once anything was written. `dismiss` does nothing while writes are pending,
 * so a closing dialog never leaves a loop writing unseen.
 */
export function useProvisionRun({ mode, rows, projects, providerTypes, projectId, projectName, notice, onClose, onSaved }: {
  mode: ProvisionMode
  rows: BulkVaultRow[]
  projects: readonly VaultProject[]
  providerTypes: readonly string[]
  projectId: string
  projectName: string
  notice: (outcomes: readonly ProviderOutcome[]) => string
  onClose: () => void
  onSaved: (notice: string) => void
}) {
  const [outcomes, setOutcomes] = useState<ProviderOutcome[]>([])
  const [created, setCreated] = useState<BulkVaultRow[] | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const planning = created ?? rows

  async function save() {
    if (pending || projectId === "" || providerTypes.length === 0) return
    setPending(true)
    setError(null)
    const kept = outcomes.filter((outcome) => providerTypes.includes(outcome.providerType))
    let latest = kept
    setOutcomes(kept)
    try {
      await executeProvisionRun(
        { mode, rows: planning, projects, providerTypes, projectId, projectName, kept },
        {
          publish: (outcome) => { latest = withOutcome(latest, outcome); setOutcomes(latest) },
          reconcile: (record) => setCreated((current) => reconcileCreated(current ?? planning, record)),
          describeFailure: failureReason,
        },
        CLIENTS
      )
      if (judgeOutcomes(latest) === "success") onSaved(notice(latest))
      else setError(outcomeError(latest))
    } finally {
      setPending(false)
    }
  }

  /** Leave the dialog: reload the page when any record was written. */
  const dismiss = () => {
    if (pending) return
    if (created === null) onClose()
    else onSaved(notice(outcomes))
  }

  return { outcomes, planning, pending, error, save, dismiss }
}
