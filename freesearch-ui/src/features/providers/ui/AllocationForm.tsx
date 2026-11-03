import { useState } from "react"
import type { FormEvent } from "react"
import { CREDENTIAL_OPERATIONS } from "@/domains/providers"
import type { Allocation, AllocationInput, Pool } from "@/domains/providers"
import { Button } from "@/shared/ui/button"
import { allocationDraft, validateAllocation } from "../model/allocationDraft"
import type { AllocationDraft } from "../model/allocationDraft"
import type { AllocationTarget } from "../model/useAllocationsController"
import { AllocationQueueFields } from "./AllocationQueueFields"
import { ALERT_CLASS, FIELD_CLASS, LABEL_CLASS } from "./formStyles"

interface AllocationFormProps {
  allocation: Allocation | null
  pools: readonly Pool[]
  pending: boolean
  error: string | null
  onSubmit: (target: AllocationTarget, input: AllocationInput) => Promise<boolean>
  onCancel: () => void
}

/**
 * Create or edit one allocation. The client blocks the contract rules
 * (max ≥ base with loans, weight ≥ 1, zero base needs best effort); the
 * server's feasibility answer shows as "Not feasible: …".
 */
export function AllocationForm({ allocation, pools, pending, error, onSubmit, onCancel }: AllocationFormProps) {
  const [draft, setDraft] = useState<AllocationDraft>(() => allocationDraft(allocation, pools[0]?.id))
  const [invalid, setInvalid] = useState<string | null>(null)
  const set = (patch: Partial<AllocationDraft>) => setDraft((previous) => ({ ...previous, ...patch }))
  const fixed = allocation !== null

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const result = validateAllocation(draft)
    setInvalid(result.ok ? null : result.message)
    if (result.ok) await onSubmit({ poolId: draft.poolId, operation: draft.operation }, result.input)
  }

  const shownError = invalid ?? error
  return (
    <form className="space-y-3 text-[13px]" onSubmit={(event) => void submit(event)} noValidate>
      {shownError !== null && <p role="alert" className={ALERT_CLASS}>{shownError}</p>}
      <div className="grid grid-cols-4 gap-3">
        <label className={LABEL_CLASS}>
          Pool
          {pools.length === 0 && !fixed ? (
            <input value={draft.poolId} disabled={pending} placeholder="Pool id" onChange={(event) => set({ poolId: event.target.value.trim() })} className={FIELD_CLASS} />
          ) : (
            <select value={draft.poolId} disabled={pending || fixed} onChange={(event) => set({ poolId: event.target.value })} className={FIELD_CLASS}>
              {!pools.some((pool) => pool.id === draft.poolId) && <option value={draft.poolId}>{draft.poolId}</option>}
              {pools.map((pool) => (<option key={pool.id} value={pool.id}>{pool.label}</option>))}
            </select>
          )}
        </label>
        <label className={LABEL_CLASS}>
          Operation
          <select value={draft.operation} disabled={pending || fixed} onChange={(event) => set({ operation: event.target.value === "fetch" ? "fetch" : "search" })} className={FIELD_CLASS}>
            {CREDENTIAL_OPERATIONS.map((op) => (<option key={op} value={op}>{op}</option>))}
          </select>
        </label>
        <label className={LABEL_CLASS}>
          Base rate
          <input type="number" min={0} value={draft.baseRate} disabled={pending} onChange={(event) => set({ baseRate: event.target.value })} className={FIELD_CLASS} />
        </label>
        <label className={LABEL_CLASS}>
          Window seconds
          <input type="number" min={1} value={draft.windowSeconds} disabled={pending} onChange={(event) => set({ windowSeconds: event.target.value })} className={FIELD_CLASS} />
        </label>
      </div>
      <fieldset className="flex flex-wrap items-end gap-4">
        <legend className={LABEL_CLASS}>Mode</legend>
        <label className="inline-flex items-center gap-2">
          <input type="radio" name="allocation-mode" checked={!draft.borrowEnabled} disabled={pending} onChange={() => set({ borrowEnabled: false })} />
          Strict cap
        </label>
        <label className="inline-flex items-center gap-2">
          <input type="radio" name="allocation-mode" checked={draft.borrowEnabled} disabled={pending} onChange={() => set({ borrowEnabled: true })} />
          Loans enabled
        </label>
        {draft.borrowEnabled && (
          <label className={LABEL_CLASS}>
            Max rate
            <input type="number" min={0} value={draft.maxRate} disabled={pending} onChange={(event) => set({ maxRate: event.target.value })} className={FIELD_CLASS} />
          </label>
        )}
        <label className={LABEL_CLASS}>
          Weight
          <input type="number" min={1} value={draft.weight} disabled={pending} onChange={(event) => set({ weight: event.target.value })} className={FIELD_CLASS} />
        </label>
        <label className="inline-flex items-center gap-2">
          <input type="checkbox" checked={draft.bestEffort} disabled={pending} onChange={(event) => set({ bestEffort: event.target.checked })} />
          Best effort
        </label>
      </fieldset>
      <AllocationQueueFields draft={draft} disabled={pending} onChange={set} />
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={pending}>Save allocation</Button>
      </div>
    </form>
  )
}
