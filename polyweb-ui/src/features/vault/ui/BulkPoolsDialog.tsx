import { useState } from "react"
import { providerTypeName } from "@/domains/providers"
import type { VaultProject } from "@/domains/vault"
import { Checkbox } from "@/shared/ui/Checkbox"
import { Field } from "@/shared/ui/Field"
import { Modal } from "@/shared/ui/Modal"
import { Select } from "@/shared/ui/select"
import { BulkDialogActions } from "./BulkDialogActions"
import { useProvisionRun } from "./useProvisionRun"
import { eligibleBulkProjects, ownedProviderTypes, summarizeOutcomes } from "../model/bulkPools"
import type { BulkVaultRow } from "../model/bulkPools"

/**
 * One-shot pool creation across several providers for one project. Each
 * selected provider resolves to its single owned key; multi-key providers
 * are blocked by name instead of picked silently, and providers unavailable
 * to the project are reported. Providers the project already holds count as
 * satisfied. Every pool is a plain local record creation — no vendor
 * request is made.
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
  const projectName = projects.find((project) => project.id === projectId)?.name ?? "project"
  const run = useProvisionRun({
    mode: "bulk", rows, projects, providerTypes: selected, projectId, projectName,
    failure: "The pools did not save. Try again", notice: summarizeOutcomes, onClose, onSaved,
  })
  const toggle = (providerType: string) =>
    setSelected((current) =>
      current.includes(providerType) ? current.filter((entry) => entry !== providerType) : [...current, providerType]
    )
  const done = run.outcomes.length > 0
  const eligible = eligibleBulkProjects(projects, selected, run.planning)
  const project = eligible.find((entry) => entry.id === projectId)
  return (
    <Modal isOpen onClose={run.dismiss} title="Bulk create pools" maxWidth="lg">
      <div className="space-y-4">
        <p>One pool per selected provider, each on its owned key, assigned to one project. Keyless providers need no API key.</p>
        <Field id="bulk-project" label="Project" hint="Only projects where you are the provider owner">
          <Select id="bulk-project" value={projectId} onValueChange={setProjectId} disabled={run.pending || done}
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
        {done && (
          <ul className="space-y-1 text-[13px]">
            {run.outcomes.map((outcome) => <li key={outcome.providerType}>{outcome.message}</li>)}
          </ul>
        )}
        {run.error && <p role="alert" className="fs-field-error">{run.error}</p>}
        <BulkDialogActions
          done={done}
          pending={run.pending}
          canSave={projectId !== "" && selected.length > 0}
          createLabel={selected.length > 1 ? `Create ${selected.length} pools` : "Create pool"}
          onDismiss={run.dismiss}
          onSave={() => void run.save()}
        />
      </div>
    </Modal>
  )
}
