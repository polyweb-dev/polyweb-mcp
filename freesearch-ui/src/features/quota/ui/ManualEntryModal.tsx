import { useState } from "react"
import type { ReactNode } from "react"
import { Modal } from "@/shared/ui/Modal"
import { ProviderLogo } from "@/shared/ui/ProviderLogo"
import { ProviderSelect } from "@/shared/ui/ProviderSelect"
import { unitLabel } from "@/services/api/mappers"
import type { BackendManualQuotaPayload } from "@/domains/dashboard/api/manualQuotaWire"
import type { ProviderConfig } from "@/domains/providers"
import type { UnitKind } from "@/shared/api/units"
import type { ManualAmountMode } from "../model/manualQuotaMath"
import type { ManualUnit } from "../model/manualQuotaUnit"
import type { BalancePrefill } from "../model/providerInfo"
import { BALANCE_ENTRY_NOTE, type CreditMode } from "../model/quotaLabels"
import type { ManualQuotaDefaults } from "../model/useQuotaForm"
import { ManualEntryForm } from "./ManualEntryForm"
import { ManualQuotaField } from "./ManualQuotaField"

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
  /** The selectable providers of the dropdown; the own provider is the default. */
  providers?: ProviderConfig[]
  /** Native entry units for each selectable provider. */
  providerUnits?: Readonly<Record<string, ManualUnit>>
  /** The observed balance per provider, which starts a new entry as an estimate. */
  observed?: Record<string, BalancePrefill>
  /** `balance` accepts the remaining balance of a USD vendor dashboard. */
  amountMode?: ManualAmountMode
  onClose: () => void
  onSave: (payload: BackendManualQuotaPayload, providerId?: string) => Promise<unknown>
  onDelete?: () => Promise<unknown>
}

interface ProviderTarget {
  id: string
  name: string
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

function unitForTarget(
  targetProviderId: string,
  providerId: string,
  currentUnit: ManualUnit,
  providerUnits?: Readonly<Record<string, ManualUnit>>,
): ManualUnit {
  const knownUnit = providerUnits?.[targetProviderId]
  if (knownUnit !== undefined) return knownUnit
  if (targetProviderId === "exa") {
    return { unitKind: "USD", displayUnit: "USD", amountMode: "balance" }
  }
  if (targetProviderId === providerId) return currentUnit
  return { unitKind: null, displayUnit: null, amountMode: "usage" }
}

/**
 * The provider field of the shell: the catalog combo of the target.
 *
 * The trigger and every option hold the logo and the name of one provider, so
 * no second badge sits beside the control. A selection retargets the form.
 */
function providerField(
  options: ProviderTarget[],
  target: ProviderTarget,
  onChange: (next: ProviderTarget) => void,
): ReactNode {
  const rows = options.map((option) => ({ value: option.id, label: option.name }))
  const nameOf = (providerId: string): string =>
    options.find((option) => option.id === providerId)?.name ?? providerId
  return (
    <ManualQuotaField
      id="manual-quota-provider"
      testId="manual-quota-provider"
      label="Provider"
      error={undefined}
      disabled={false}
      render={(inputProps) => (
        <ProviderSelect
          id={inputProps.id}
          testId={inputProps["data-testid"]}
          value={target.id}
          options={rows}
          onValueChange={(next) => onChange({ id: next, name: nameOf(next) })}
        />
      )}
    />
  )
}

/**
 * Reusable balance entry (Brave first; Exa/Parallel reuse it with USD units).
 * Mount it only while open (or key it per session): field state initialises from
 * `defaults` at mount. The vendor throttle headline is never rewritten here.
 *
 * The provider field retargets the entry. The form of the target is keyed by its
 * provider, so a new target starts from its own saved entry or from its own
 * observed balance.
 */
function editingEntry(own: boolean, defaults: ManualQuotaDefaults | null): boolean {
  return own && Boolean(defaults?.allowance)
}

function defaultsForTarget(
  own: boolean,
  defaults: ManualQuotaDefaults | null,
): ManualQuotaDefaults | null {
  return own ? defaults : null
}

/** The selectable targets: the payload list, else the own provider alone. */
function targetsOf(
  providers: ProviderConfig[] | undefined,
  providerId: string,
  providerName: string,
): ProviderTarget[] {
  if (providers === undefined) return [{ id: providerId, name: providerName }]
  return providers
}

/** The form callbacks: an absent delete callback adds no property. */
function deleteProp(onDelete?: () => Promise<unknown>): { onDelete?: () => Promise<unknown> } {
  if (onDelete === undefined) return {}
  return { onDelete }
}

/** The save of the own provider: the payload alone reaches the caller. */
function ownSave(
  onSave: (payload: BackendManualQuotaPayload, providerId?: string) => Promise<unknown>,
): (payload: BackendManualQuotaPayload) => Promise<unknown> {
  return (payload) => onSave(payload)
}

/** The save of another target: the payload and the target reach the caller. */
function targetSave(
  onSave: (payload: BackendManualQuotaPayload, providerId?: string) => Promise<unknown>,
  providerId: string,
): (payload: BackendManualQuotaPayload) => Promise<unknown> {
  return (payload) => onSave(payload, providerId)
}

/** The save of the selected target: the own provider alone receives the payload. */
function saveFor(
  onSave: (payload: BackendManualQuotaPayload, providerId?: string) => Promise<unknown>,
  own: boolean,
  providerId: string,
): (payload: BackendManualQuotaPayload) => Promise<unknown> {
  if (own) return ownSave(onSave)
  return targetSave(onSave, providerId)
}

export function ManualEntryModal(props: ManualEntryVariant): ReactNode {
  const {
    open,
    providerId,
    providerName,
    unitKind,
    displayUnit = null,
    defaults = null,
    amountMode = "usage",
    creditMode = "free",
    providers,
    providerUnits,
    observed,
    onClose,
    onSave,
    onDelete,
  } = props
  const currentUnit = { unitKind, displayUnit, amountMode }
  const options = targetsOf(providers, providerId, providerName)
  const [target, setTarget] = useState<ProviderTarget>({ id: providerId, name: providerName })
  const targetUnit = unitForTarget(target.id, providerId, currentUnit, providerUnits)
  const rawNoun = unitLabel(targetUnit.unitKind, targetUnit.displayUnit)
  // Presentation fallback only; amount handling still uses the target unit.
  const noun = rawNoun === "legacy" ? "units" : rawNoun
  const placeholders = placeholdersFor(targetUnit.unitKind, targetUnit.amountMode)
  const own = target.id === providerId
  const isEditing = editingEntry(own, defaults)
  // A late entry read remounts the form, so the saved values win over the estimate.
  const formKey =
    [target.id, targetUnit.unitKind ?? "legacy", targetUnit.displayUnit ?? "", targetUnit.amountMode].join(":") +
    (isEditing ? "-entry" : "-empty")

  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      maxWidth="md"
      title={<><ProviderLogo providerId={target.id} name={target.name} />{"Balance for " + target.name}</>}
      subtitle={BALANCE_ENTRY_NOTE}
    >
      <ManualEntryForm
        key={formKey}
        providerId={target.id}
        noun={noun}
        placeholders={placeholders}
        defaults={defaultsForTarget(own, defaults)}
        observed={observed?.[target.id] ?? null}
        creditMode={creditMode}
        amountMode={targetUnit.amountMode}
        providerField={providerField(options, target, setTarget)}
        onSave={saveFor(onSave, own, target.id)}
        {...deleteProp(onDelete)}
        onClose={onClose}
      />
    </Modal>
  )
}
