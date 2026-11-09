import type { KeyPool } from "@/domains/vault"
import { POOL_BUDGET_HELP } from "@/domains/vault"
import { BudgetFields } from "@/shared/ui/BudgetFields"
import { Switch } from "@/shared/ui/Switch"
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
    <Switch checked={enabled} onChange={setEnabled} label="Budget" />
    {enabled && <div className="space-y-2">
      <BudgetFields id="pool-budget" label="Budget (USD)" amount={budget} onAmountChange={setBudget}
        period={period} onPeriodChange={setPeriod} />
      {pool?.budget && <PoolBudgetUsage pool={pool} />}
      <p className="fs-hint">{POOL_BUDGET_HELP}</p>
    </div>}
  </>
}
