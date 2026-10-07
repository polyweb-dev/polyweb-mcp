import { useState } from "react"
import type { ReactNode } from "react"
import { Modal } from "@/shared/ui/Modal"
import { unitLabel } from "@/services/api/mappers"
import type { BackendManualQuotaPayload } from "@/domains/dashboard/api/manualQuotaWire"
import type { UnitKind } from "@/shared/api/units"
import { formatPercent1dp, type ManualAmountMode } from "../model/manualQuotaMath"
import { BALANCE_ENTRY, BALANCE_ENTRY_NOTE, type CreditMode } from "../model/quotaLabels"
import { useQuotaForm, type ManualQuotaDefaults } from "../model/useQuotaForm"
import { ManualQuotaFields } from "./ManualQuotaFields"
import { ManualQuotaActions } from "./ManualQuotaActions"

/** Native anchor entry: the current manual form and its one modal shell. */
export interface ManualEntryVariant {
  mode?: "manual"
  open: boolean
  providerId: string
  providerName: string
  unitKind: UnitKind | null
  displayUnit?: string | null
  defaults?: ManualQuotaDefaults | null
  /** The credit tier of the entry. The API carries no tier field, so it shows only. */
  creditMode?: CreditMode
  /** `balance` accepts the remaining balance of a USD vendor dashboard. */
  amountMode?: ManualAmountMode
  onClose: () => void
  onSave: (payload: BackendManualQuotaPayload) => Promise<unknown>
  onDelete?: () => Promise<unknown>
}

function placeholdersFor(
  unitKind: UnitKind | null,
  amountMode: ManualAmountMode,
): { allowance: string; used: string } {
  if (amountMode === "balance") return { allowance: "5.00", used: "4.12" }
  if (unitKind === "USD") return { allowance: "5.00", used: "0.88" }
  if (unitKind === "REQUEST") return { allowance: "1000", used: "120" }
  if (unitKind === "CREDIT") return { allowance: "100000", used: "12000" }
  return { allowance: "100", used: "12" }
}

/**
 * Reusable balance entry (Brave first; Exa/Parallel reuse it with USD units).
 * Mount it only while open (or key it per session): field state initialises from
 * `defaults` at mount. The vendor throttle headline is never rewritten here.
 */
export function ManualEntryModal(props: ManualEntryVariant): ReactNode {
  const {
    open,
    providerId,
    providerName,
    unitKind,
    displayUnit = null,
    defaults = null,
    amountMode = "usage",
    onClose,
    onSave,
    onDelete,
  } = props
  const rawNoun = unitLabel(unitKind, displayUnit)
  // Presentation fallback only; branching logic still uses unitKind.
  const noun = rawNoun === "legacy" ? "units" : rawNoun
  const placeholders = placeholdersFor(unitKind, amountMode)
  const isEditing = Boolean(defaults?.allowance)
  const [creditMode, setCreditMode] = useState<CreditMode>(props.creditMode ?? "free")
  const form = useQuotaForm(
    defaults,
    {
      onSave,
      ...(onDelete !== undefined ? { onDelete } : {}),
      onClose,
    },
    amountMode
  )

  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      maxWidth="sm"
      title={(isEditing ? "Update " + BALANCE_ENTRY.toLowerCase() : BALANCE_ENTRY) + " — " + providerName}
      subtitle={BALANCE_ENTRY_NOTE}
    >
      <form onSubmit={(event) => void form.handleSubmit(event)} noValidate>
        <ManualQuotaFields
          providerId={providerId}
          noun={noun}
          placeholders={placeholders}
          fields={form.fields}
          fieldErrors={form.fieldErrors}
          pending={form.pending}
          mode={creditMode}
          onModeChange={setCreditMode}
          onChange={form.setField}
          amountMode={amountMode}
        />
        <p
          data-testid="manual-quota-preview"
          aria-live="polite"
          className="mt-3 text-[12px] text-[var(--muted)] tnum"
        >
          {form.preview === null
            ? "Enter an allowance and " +
              (amountMode === "balance" ? "a balance" : "usage") +
              " to preview the estimated percentage."
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
