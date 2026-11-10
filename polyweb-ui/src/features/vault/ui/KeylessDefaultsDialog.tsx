import { useState } from "react"
import { keylessProviderTypes, providerTypeName } from "@/domains/providers"
import type { VaultProject } from "@/domains/vault"
import { Field } from "@/shared/ui/Field"
import { Modal } from "@/shared/ui/Modal"
import { Select } from "@/shared/ui/select"
import { BulkDialogActions } from "./BulkDialogActions"
import { useProvisionRun } from "./useProvisionRun"
import { summarizeOutcomes } from "../model/bulkPools"
import type { BulkVaultRow, ProviderOutcome } from "../model/bulkPools"

/**
 * One-shot provisioning of the supported keyless free-tier pools for one
 * project. For each supported keyless provider the dialog skips it when the
 * project already holds any pool of it (keyed or keyless), otherwise reuses
 * the owned keyless key or creates one with no secret, then creates the
 * pool — reruns create nothing new. Keyed pools and ownership are
 * preserved. Every call is a plain local record write — no vendor request is
 * made.
 */
export function KeylessDefaultsDialog({ rows, projects, onClose, onSaved }: {
  rows: BulkVaultRow[]
  projects: readonly VaultProject[]
  onClose: () => void
  onSaved: (notice: string) => void
}) {
  const supported = keylessProviderTypes()
  const [projectId, setProjectId] = useState("")
  const projectName = projects.find((project) => project.id === projectId)?.name ?? "project"
  const notice = (outcomes: readonly ProviderOutcome[]) =>
    outcomes.length > 0 && outcomes.every((outcome) => outcome.status === "created")
      ? `Keyless defaults ready for ${projectName}`
      : `Keyless defaults for ${projectName}: ${summarizeOutcomes(outcomes)}`
  const run = useProvisionRun({
    mode: "defaults", rows, projects, providerTypes: supported, projectId, projectName,
    failure: "The defaults did not save. Try again", notice, onClose, onSaved,
  })
  const done = run.outcomes.length > 0
  return (
    <Modal isOpen onClose={run.dismiss} title="Keyless defaults" maxWidth="lg">
      <div className="space-y-4">
        <p>Create the supported keyless free-tier pools ({supported.map(providerTypeName).join(", ")}) for one project. No API key is needed; existing pools and keys are reused.</p>
        <Field id="defaults-project" label="Project" hint="Only projects where you are the provider owner">
          <Select id="defaults-project" value={projectId} onValueChange={setProjectId} disabled={run.pending || done}
            options={projects.map((entry) => ({ value: entry.id, label: entry.name }))} placeholder="No available projects" />
        </Field>
        {supported.length === 0 && <p>No supported keyless providers are configured</p>}
        {done && (
          <ul className="space-y-1 text-[13px]">
            {run.outcomes.map((outcome) => <li key={outcome.providerType}>{outcome.message}</li>)}
          </ul>
        )}
        {run.error && <p role="alert" className="fs-field-error">{run.error}</p>}
        <BulkDialogActions
          done={done}
          pending={run.pending}
          canSave={projectId !== "" && supported.length > 0}
          createLabel="Create defaults"
          onDismiss={run.dismiss}
          onSave={() => void run.save()}
        />
      </div>
    </Modal>
  )
}
