import { Modal } from "@/components/common/Modal"
import { unitLabel } from "@/services/api/mappers"
import type { BackendManualQuotaPayload } from "@/services/api/backendTypes"
import type { UnitKind } from "@/types/freesearch"
import { formatPercent1dp } from "../model/manualQuotaMath"
import { useQuotaForm, type ManualQuotaDefaults } from "../model/useQuotaForm"
import { ManualQuotaFields } from "./ManualQuotaFields"
import { ManualQuotaActions } from "./ManualQuotaActions"

export type { ManualQuotaDefaults }

export interface ManualQuotaModalProps {
  open: boolean
  providerId: string
  providerName: string
  unitKind: UnitKind | null
  displayUnit?: string | null
  defaults?: ManualQuotaDefaults | null
  onClose: () => void
  onSave: (payload: BackendManualQuotaPayload) => Promise<unknown>
  onDelete?: () => Promise<unknown>
}

function placeholdersFor(unitKind: UnitKind | null): { allowance: string; used: string } {
  if (unitKind === "USD") return { allowance: "5.00", used: "0.88" }
  if (unitKind === "REQUEST") return { allowance: "1000", used: "120" }
  if (unitKind === "CREDIT") return { allowance: "100000", used: "12000" }
  return { allowance: "100", used: "12" }
}

/**
 * Reusable manual billing entry (Brave first; Exa/Parallel reuse it with
 * USD units). Mount it only while open (or key it per session): field state
 * initialises from `defaults` at mount. The vendor throttle headline is
 * never rewritten here — the saved window renders as an estimated overlay.
 */
export function ManualQuotaModal(props: ManualQuotaModalProps) {
  const {
    open,
    providerId,
    providerName,
    unitKind,
    displayUnit = null,
    defaults = null,
    onClose,
    onSave,
    onDelete,
  } = props
  const rawNoun = unitLabel(unitKind, displayUnit)
  // Presentation fallback only; branching logic still uses unitKind.
  const noun = rawNoun === "legacy" ? "units" : rawNoun
  const placeholders = placeholdersFor(unitKind)
  const isEditing = Boolean(defaults?.allowance)
  const form = useQuotaForm(defaults, { onSave, onDelete, onClose })

  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      maxWidth="sm"
      title={(isEditing ? "Update usage" : "Set budget") + " — " + providerName}
      subtitle="Manual billing window. Estimated locally; not a vendor balance."
    >
      <form onSubmit={(event) => void form.handleSubmit(event)} noValidate>
        <ManualQuotaFields
          providerId={providerId}
          noun={noun}
          placeholders={placeholders}
          fields={form.fields}
          fieldErrors={form.fieldErrors}
          pending={form.pending}
          onChange={form.setField}
        />
        <p
          data-testid="manual-quota-preview"
          aria-live="polite"
          className="mt-3 text-[12px] text-[var(--muted)] tnum"
        >
          {form.preview === null
            ? "Enter an allowance and usage to preview the estimated percentage."
            : "Estimated " + formatPercent1dp(form.preview) + "% remaining"}
        </p>
        {form.saveError && (
          <p
            role="alert"
            data-testid="manual-quota-error"
            className="mt-3 p-2.5 rounded border border-[var(--status-danger)]/40 bg-[var(--surface)] text-[13px]"
            style={{ color: "var(--status-danger)" }}
          >
            {form.saveError}
          </p>
        )}
        <ManualQuotaActions
          isEditing={isEditing}
          canDelete={Boolean(onDelete)}
          pending={form.pending}
          saving={form.saving}
          deleting={form.deleting}
          onCancel={onClose}
          onDelete={() => void form.handleDelete()}
        />
      </form>
    </Modal>
  )
}
