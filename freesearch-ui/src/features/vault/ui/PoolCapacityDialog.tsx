import { useState } from "react"
import type { FormEvent } from "react"
import { providerIdentity, providerTypeName, supportedOperationsOf } from "@/domains/providers"
import { createKeyPool, updateKeyPool } from "@/domains/vault"
import type { KeyPool, KeyPoolInput, PoolOperation, VaultKey, VaultProject } from "@/domains/vault"
import { ApiError } from "@/shared/api/http"
import { Button } from "@/shared/ui/button"
import { Checkbox } from "@/shared/ui/Checkbox"
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog"
import { Field } from "@/shared/ui/Field"
import { FormActions } from "@/shared/ui/FormActions"
import { Modal } from "@/shared/ui/Modal"
import { NumericField } from "@/shared/ui/NumericField"
import { ProviderLogo } from "@/shared/ui/ProviderLogo"
import { Select } from "@/shared/ui/select"
import { TextField } from "@/shared/ui/TextField"
import { Switch } from "@/shared/ui/Switch"
import { useFreeProvider } from "../model/useFreeProvider"
import { PoolBudgetFields } from "./PoolBudgetFields"

const operations: readonly PoolOperation[] = ["search", "fetch"]
const operationName = (operation: PoolOperation) => operation === "search" ? "Search" : "Fetch"

function initialPoolRate(item: VaultKey, pool?: KeyPool) {
  return {
    rate: pool?.rate.limit?.toString() ?? item.capacity?.limit?.toString() ?? "60",
    windowSeconds: pool?.rate.window_seconds ?? item.capacity?.window_seconds ?? 60,
  }
}

function initialOperationRates(pool?: KeyPool) {
  return {
    searchRate: pool?.operation_limits?.search?.toString() ?? "60",
    fetchRate: pool?.operation_limits?.fetch?.toString() ?? "60",
  }
}

function initialPoolBudget(pool?: KeyPool) {
  return {
    budget: pool?.budget?.limit.toString() ?? "",
    budgetEnabled: pool?.budget != null,
    period: pool?.budget?.period ?? "month",
    separate: pool?.operation_limits != null,
  }
}

function invalidBudget(enabled: boolean, budget: string): boolean {
  return enabled && (!budget || !Number.isFinite(Number(budget)) || Number(budget) <= 0)
}

function initialPoolSelection(item: VaultKey, pool: KeyPool | undefined, eligible: readonly VaultProject[]) {
  return {
    projectId: eligible[0]?.id ?? "",
    label: pool?.label ?? "",
    selected: pool?.operations ?? supportedOperationsOf(item.provider_type),
  }
}

function poolName(label: string, project: VaultProject | undefined, item: VaultKey): string {
  return label || (project ? `${project.name} - ${providerTypeName(item.provider_type)}` : "")
}

function renderConfirmation({ confirm, item, projects, pool, selected, pending, close, save }: {
  confirm: PoolOperation | null
  item: VaultKey
  projects: readonly VaultProject[]
  pool?: KeyPool
  selected: PoolOperation[]
  pending: boolean
  close: () => void
  save: () => void
}) {
  if (!confirm) return null
  const remaining = selected.find((operation) => pool?.operations.includes(operation))
  const stays = remaining ? ` ${operationName(remaining)} stays on.` : ""
  return <ConfirmDialog open title={`Remove ${operationName(confirm)} from ${pool?.label ?? "this pool"}`} message={`${providerTypeName(item.provider_type)} leaves the ${operationName(confirm)} order of ${projects.find((entry) => entry.id === pool?.project_id)?.name ?? "this project"}.${stays}`} confirmLabel={`Remove ${operationName(confirm)}`} pending={pending} onClose={close} onConfirm={save} />
}

function renderActions({ pool, pending, selected, projectId, onClose }: {
  pool?: KeyPool
  pending: boolean
  selected: PoolOperation[]
  projectId: string
  onClose: () => void
}) {
  return <FormActions><Button type="button" variant="outline" size="form" onClick={onClose}>Cancel</Button><Button type="submit" size="form" disabled={pending || selected.length === 0 || (!pool && !projectId)}>{pool ? "Save pool" : "Create pool"}</Button></FormActions>
}

function renderOperations(item: VaultKey, selected: PoolOperation[], setSelected: (value: PoolOperation[]) => void) {
  return <fieldset><legend className="fs-label">Allowed operations</legend>
    <div className="flex items-center gap-4">{operations.map((operation) => {
      const supported = supportedOperationsOf(item.provider_type).includes(operation)
      if (!supported) return <span key={operation} className="text-[var(--muted)]">{providerTypeName(item.provider_type)} has no {operationName(operation)}</span>
      return <Checkbox key={operation} label={operationName(operation)} checked={selected.includes(operation)} onChange={(checked) => setSelected(checked ? [...selected, operation] : selected.filter((entry) => entry !== operation))} />
    })}</div>
    {selected.length === 0 && <p role="alert" className="fs-field-error">Select at least one operation</p>}
  </fieldset>
}

function renderOperationRates({ separate, setSeparate, selected, searchRate, setSearchRate, fetchRate, setFetchRate }: {
  separate: boolean
  setSeparate: (value: boolean) => void
  selected: PoolOperation[]
  searchRate: string
  setSearchRate: (value: string) => void
  fetchRate: string
  setFetchRate: (value: string) => void
}) {
  return <div className="space-y-3">
    <Switch checked={separate} onChange={setSeparate} label="Limit Search and Fetch separately" />
    {separate && selected.includes("search") && <NumericField id="search-rate" label="Search requests" min="1" value={searchRate} onChange={setSearchRate} />}
    {separate && selected.includes("fetch") && <NumericField id="fetch-rate" label="Fetch requests" min="1" value={fetchRate} onChange={setFetchRate} />}
  </div>
}

export function PoolCapacityDialog({ item, pool, projects, onClose, onSaved }: {
  item: VaultKey
  pool?: KeyPool
  projects: readonly VaultProject[]
  onClose: () => void
  onSaved: () => void
}) {
  const free = useFreeProvider(item.provider_type)
  const eligible = projects.filter((project) => project.available_providers.includes(item.provider_type))
  const initialRate = initialPoolRate(item, pool)
  const initialOperations = initialOperationRates(pool)
  const initialBudget = initialPoolBudget(pool)
  const initialSelection = initialPoolSelection(item, pool, eligible)
  const [projectId, setProjectId] = useState(initialSelection.projectId)
  const [label, setLabel] = useState(initialSelection.label)
  const [selected, setSelected] = useState<PoolOperation[]>(initialSelection.selected)
  const [rate, setRate] = useState(initialRate.rate)
  const [windowSeconds, setWindowSeconds] = useState(initialRate.windowSeconds)
  const [budget, setBudget] = useState(initialBudget.budget)
  const [budgetEnabled, setBudgetEnabled] = useState(initialBudget.budgetEnabled)
  const hasBudget = budgetEnabled && !free
  const [period, setPeriod] = useState(initialBudget.period)
  const [separate, setSeparate] = useState(initialBudget.separate)
  const [searchRate, setSearchRate] = useState(initialOperations.searchRate)
  const [fetchRate, setFetchRate] = useState(initialOperations.fetchRate)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<PoolOperation | null>(null)
  const project = eligible.find((entry) => entry.id === projectId)
  const name = poolName(label, project, item)

  function input(): KeyPoolInput {
    const limits: Partial<Record<PoolOperation, number>> = {}
    if (separate && selected.includes("search")) limits.search = Number(searchRate)
    if (separate && selected.includes("fetch")) limits.fetch = Number(fetchRate)
    return {
      label: name.trim(), ...(pool ? {} : { project_id: projectId }),
      rate: { limit: rate === "" ? null : Number(rate), window_seconds: windowSeconds },
      budget: !hasBudget || budget === "" ? null : { limit: Number(budget), period },
      operations: selected, operation_limits: separate ? limits : null,
    }
  }

  async function save() {
    setPending(true)
    setError(null)
    try {
      if (pool) await updateKeyPool(pool.id, input())
      else await createKeyPool(item.id, input())
      onSaved()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && /duplicate|already/i.test(err.detail)) setError("This project already has a pool for this provider.")
      else if (err instanceof ApiError && err.status === 409) setError("The pool did not save. The pool limits are more than the key limit.")
      else setError("The pool did not save. Try again.")
    } finally {
      setPending(false)
      setConfirm(null)
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    const rates = [rate, ...(separate ? selected.map((op) => op === "search" ? searchRate : fetchRate) : [])]
    if (!name.trim() || invalidBudget(hasBudget, budget) || (separate && selected.some((op) => !(op === "search" ? searchRate : fetchRate))) || rates.some((value) => value !== "" && (!Number.isInteger(Number(value)) || Number(value) <= 0))) {
      setError("Enter a pool name and valid limits.")
      return
    }
    const removed = pool?.project_id ? pool.operations.filter((op) => !selected.includes(op)) : []
    if (removed[0]) setConfirm(removed[0])
    else void save()
  }

  return (
    <>
      <Modal isOpen onClose={onClose} title={<><ProviderLogo providerId={providerIdentity(item.provider_type).id} name={providerTypeName(item.provider_type)} />{pool ? `Edit ${pool.label}` : `Create pool from ${item.label}`}</>} maxWidth="lg">
        <form onSubmit={submit} className="space-y-4">
          {!pool && <Field id="pool-project" label="Project" hint="Only projects where you are the provider owner">
            <Select id="pool-project" value={projectId} onValueChange={(value) => { setProjectId(value); setLabel("") }}
              options={eligible.map((entry) => ({ value: entry.id, label: entry.name }))} placeholder="No available projects" />
          </Field>}
          {!pool && eligible.length === 0 && <p>You are not the provider owner of a project without this provider</p>}
          <TextField id="pool-label" label="Pool name" type="text" value={name} onChange={setLabel} />
          {renderOperations(item, selected, setSelected)}
          <div className="grid grid-cols-2 gap-3">
            {!separate && <NumericField id="pool-rate" label="Request rate" min="1" value={rate} onChange={setRate} />}
            <Field id="pool-window" label="Rate unit"><Select id="pool-window" value={String(windowSeconds)} onValueChange={(value) => setWindowSeconds(Number(value))}
              options={[{ value: "1", label: "Per second" }, { value: "60", label: "Per minute" }, { value: "3600", label: "Per hour" }]} /></Field>
          </div>
          {supportedOperationsOf(item.provider_type).length > 1 && renderOperationRates({ separate, setSeparate, selected, searchRate, setSearchRate, fetchRate, setFetchRate })}
          {!free && <PoolBudgetFields enabled={hasBudget} setEnabled={setBudgetEnabled} budget={budget} setBudget={setBudget} period={period} setPeriod={setPeriod} pool={pool} />}
          {error && <p role="alert" className="fs-field-error">{error}</p>}
          {renderActions({ pool, pending, selected, projectId, onClose })}
        </form>
      </Modal>
      {renderConfirmation({ confirm, item, projects, pool, selected, pending, close: () => setConfirm(null), save: () => void save() })}
    </>
  )
}
