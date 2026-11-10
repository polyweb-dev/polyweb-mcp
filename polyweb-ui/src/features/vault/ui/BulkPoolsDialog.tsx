import { useState } from "react"
import { providerTypeName } from "@/domains/providers"
import { createKeyPool } from "@/domains/vault"
import type { KeyPool, VaultProject } from "@/domains/vault"
import { Button } from "@/shared/ui/button"
import { Checkbox } from "@/shared/ui/Checkbox"
import { Field } from "@/shared/ui/Field"
import { FormActions } from "@/shared/ui/FormActions"
import { Modal } from "@/shared/ui/Modal"
import { Select } from "@/shared/ui/select"
import {
  defaultPoolInputForKey,
  eligibleBulkProjects,
  ownedProviderTypes,
  planBulkProvider,
} from "../model/bulkPools"
import type { BulkVaultRow } from "../model/bulkPools"

/** One per-provider outcome line: created, skipped as assigned, or blocked. */
interface BulkResult {
  providerType: string
  message: string
}

/**
 * One-shot pool creation across several providers for one project. Each
 * selected provider resolves to its single owned key; multi-key providers
 * fail loudly by name instead of picking silently, and providers unavailable
 * to the project are left out. Every pool is a plain local record creation —
 * no vendor request is made.
 */
export function BulkPoolsDialog({ rows, projects, onClose, onSaved }: {
  rows: BulkVaultRow[]
  projects: readonly VaultProject[]
  onClose: () => void
  onSaved: (notice: string) => void
}) {
  const candidates = ownedProviderTypes(rows)
  const [selected, setSelected] = useState<string[]>(candidates)
  const [projectId, setProjectId] = useState("")
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [results, setResults] = useState<BulkResult[] | null>(null)
/** Run one bulk-selected provider: plan it, then create its pool. Returns the
 * outcome line and whether a pool was created.
 */
async function runBulkProvider(
  rows: BulkVaultRow[],
  projects: readonly VaultProject[],
  providerType: string,
  projectId: string
): Promise<{ outcome: BulkResult; created: boolean }> {
  const plan = planBulkProvider(rows, projects, providerType, projectId)
  if (plan.key === undefined) return { outcome: plan.outcome, created: false }
  const createdPool: KeyPool = await createKeyPool(plan.key.id, defaultPoolInputForKey(plan.key, projectId))
  return {
    outcome: { providerType, message: `${providerTypeName(providerType)}: created pool ${createdPool.label}` },
    created: true,
  }
}
  const toggle = (providerType: string) =>
    setSelected((current) =>
      current.includes(providerType) ? current.filter((entry) => entry !== providerType) : [...current, providerType]
    )
  const createLabel = (count: number) => (count === 1 ? "Create pool" : `Create ${count} pools`)
  async function save() {
    if (pending || !projectId || selected.length === 0) return
    setPending(true)
    setError(null)
    setResults(null)
    try {
      const outcomes: BulkResult[] = []
      let created = 0
      for (const providerType of selected) {
        const stepped = await runBulkProvider(rows, projects, providerType, projectId)
        outcomes.push(stepped.outcome)
        if (stepped.created) created += 1
      }
      setResults(outcomes)
      if (created > 0) {
        const skipped = outcomes.length - created
        onSaved(skipped === 0 ? `Created ${created} ${created === 1 ? "pool" : "pools"}` : `Created ${created}, skipped ${skipped} already assigned`)
      } else setError("No pools were created. Resolve each provider above and try again")
    } catch {
      setError("The pools did not save. Try again")
    } finally {
      setPending(false)
    }
  }
  const eligible = eligibleBulkProjects(projects, selected)
  const project = eligible.find((entry) => entry.id === projectId)
  return (
    <Modal isOpen onClose={onClose} title="Bulk create pools" maxWidth="lg">
      <div className="space-y-4">
        <p>One pool per selected provider, each on its owned key, assigned to one project. Keyless providers need no API key.</p>
        <Field id="bulk-project" label="Project" hint="Only projects where you are the provider owner">
          <Select id="bulk-project" value={projectId} onValueChange={setProjectId}
            options={eligible.map((entry) => ({ value: entry.id, label: entry.name }))} placeholder="No available projects" />
        </Field>
        {project === undefined && projectId !== "" && <p>Select a project available for every selected provider</p>}
        <fieldset>
          <legend className="fs-label">Providers</legend>
          <div className="flex flex-col gap-2">
            {candidates.map((providerType) => (
              <Checkbox key={providerType} label={providerTypeName(providerType)} checked={selected.includes(providerType)} onChange={() => toggle(providerType)} />
            ))}
          </div>
          {candidates.length === 0 && <p>You have no keys yet. Add a key first</p>}
          {selected.length === 0 && <p role="alert" className="fs-field-error">Select at least one provider</p>}
        </fieldset>
        {results !== null && (
          <ul className="space-y-1 text-[13px]">
            {results.map((result) => <li key={result.providerType}>{result.message}</li>)}
          </ul>
        )}
        {error && <p role="alert" className="fs-field-error">{error}</p>}
        <FormActions>
          <Button type="button" variant="outline" size="form" onClick={onClose}>Cancel</Button>
          <Button type="button" size="form" pending={pending} disabled={pending || !projectId || selected.length === 0} onClick={() => void save()}>{createLabel(Math.max(selected.length, 1))}</Button>
        </FormActions>
      </div>
    </Modal>
  )
}
