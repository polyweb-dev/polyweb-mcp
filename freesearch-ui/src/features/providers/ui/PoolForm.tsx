import { useState } from "react"
import type { FormEvent } from "react"
import { POOL_STATUSES, UPSTREAM_SCOPES, credentialProviderTypes, providerTypeName } from "@/domains/providers"
import type { Pool, PoolInput } from "@/domains/providers"
import { Button } from "@/shared/ui/button"
import { poolDraft, validatePool } from "../model/poolDraft"
import type { PoolDraft } from "../model/poolDraft"
import { PoolConstraintRows } from "./PoolConstraintRows"
import { ALERT_CLASS, FIELD_CLASS, LABEL_CLASS } from "./formStyles"

interface PoolFormProps {
  pool: Pool | null
  pending: boolean
  error: string | null
  onSubmit: (input: PoolInput) => Promise<boolean>
  onCancel: () => void
}

/** Create or edit one pool; the provider is fixed once created. */
export function PoolForm({ pool, pending, error, onSubmit, onCancel }: PoolFormProps) {
  const providerTypes = credentialProviderTypes()
  const [draft, setDraft] = useState<PoolDraft>(() => poolDraft(pool, providerTypes[0] ?? ""))
  const [invalid, setInvalid] = useState<string | null>(null)
  const set = (patch: Partial<PoolDraft>) => setDraft((previous) => ({ ...previous, ...patch }))

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const result = validatePool(draft)
    setInvalid(result.ok ? null : result.message)
    if (result.ok) await onSubmit(result.input)
  }

  const shownError = invalid ?? error
  return (
    <form className="space-y-3 text-[13px]" onSubmit={(event) => void submit(event)} noValidate>
      {shownError !== null && <p role="alert" className={ALERT_CLASS}>{shownError}</p>}
      <div className="grid grid-cols-2 gap-3">
        <label className={LABEL_CLASS}>
          Provider
          <select value={draft.providerType} disabled={pending || pool !== null} onChange={(event) => set({ providerType: event.target.value })} className={FIELD_CLASS}>
            {providerTypes.map((type) => (<option key={type} value={type}>{providerTypeName(type)}</option>))}
          </select>
        </label>
        <label className={LABEL_CLASS}>
          Label
          <input value={draft.label} maxLength={100} disabled={pending} onChange={(event) => set({ label: event.target.value })} className={FIELD_CLASS} />
        </label>
        <label className={LABEL_CLASS}>
          Upstream scope
          <select value={draft.upstreamScope} disabled={pending} onChange={(event) => set({ upstreamScope: UPSTREAM_SCOPES.find((scope) => scope === event.target.value) ?? draft.upstreamScope })} className={FIELD_CLASS}>
            {UPSTREAM_SCOPES.map((scope) => (<option key={scope} value={scope}>{scope}</option>))}
          </select>
        </label>
        <label className={LABEL_CLASS}>
          Pool key
          <input value={draft.poolKey} maxLength={200} disabled={pending} onChange={(event) => set({ poolKey: event.target.value })} className={FIELD_CLASS} />
        </label>
      </div>
      <PoolConstraintRows rows={draft.constraints} disabled={pending} onChange={(constraints) => set({ constraints })} />
      <div className="grid grid-cols-3 gap-3">
        <label className={LABEL_CLASS}>
          Max concurrency
          <input type="number" min={0} value={draft.maxConcurrency} disabled={pending} onChange={(event) => set({ maxConcurrency: event.target.value })} className={FIELD_CLASS} />
        </label>
        <label className={LABEL_CLASS}>
          Max queued requests
          <input type="number" min={0} value={draft.maxQueuedRequests} disabled={pending} onChange={(event) => set({ maxQueuedRequests: event.target.value })} className={FIELD_CLASS} />
        </label>
        {pool !== null && (
          <label className={LABEL_CLASS}>
            Status
            <select value={draft.status} disabled={pending} onChange={(event) => set({ status: POOL_STATUSES.find((status) => status === event.target.value) ?? draft.status })} className={FIELD_CLASS}>
              {POOL_STATUSES.map((status) => (<option key={status} value={status}>{status}</option>))}
            </select>
          </label>
        )}
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={pending}>Save pool</Button>
      </div>
    </form>
  )
}
