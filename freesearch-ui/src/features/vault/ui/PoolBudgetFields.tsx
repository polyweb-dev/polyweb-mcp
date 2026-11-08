import type { KeyPool } from "@/domains/vault"
import { Checkbox } from "@/shared/ui/Checkbox"
import { Field } from "@/shared/ui/Field"
import { Select } from "@/shared/ui/select"
import { PoolBudgetUsage } from "./PoolBudgetUsage"

export function PoolBudgetFields({ enabled, setEnabled, budget, setBudget, period, setPeriod, pool }: {
  enabled: boolean
  setEnabled: (value: boolean) => void
  budget: string
  setBudget: (value: string) => void
  period: "day" | "week" | "month"
  setPeriod: (value: "day" | "week" | "month") => void
  pool?: KeyPool
}) {
  return <>
    <Checkbox checked={enabled} onChange={setEnabled} label="Add a budget" />
    {enabled && <div className="space-y-2">
      <div className="grid grid-cols-2 gap-3">
        <Field id="pool-budget" label="Budget (USD)">
          <div className="relative">
            <span aria-hidden="true" className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-[var(--muted)]">$</span>
            <input id="pool-budget" className="fs-input tnum pl-7" type="number" min="0" step="0.01" value={budget} onChange={(event) => setBudget(event.target.value)} />
          </div>
        </Field>
        <Field id="budget-period" label="Budget period"><Select id="budget-period" value={period}
          onValueChange={(value) => setPeriod(value === "day" || value === "week" ? value : "month")}
          options={[{ value: "day", label: "Per day" }, { value: "week", label: "Per week" }, { value: "month", label: "Per month" }]} /></Field>
      </div>
      {pool?.budget && <PoolBudgetUsage pool={pool} />}
      <p className="fs-hint whitespace-nowrap">Calls with no known cost do not count. Resets each period</p>
    </div>}
  </>
}
