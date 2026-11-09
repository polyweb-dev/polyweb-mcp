import type { OrderOperation, OrderStrategy, OperationOrder } from "@/domains/routing"
import { Select } from "@/shared/ui/select"
import { orderStrategyOptions } from "../model/orderStrategyOptions"

export function ProviderOrderToolbar(props: {
  operation: OrderOperation
  order: OperationOrder
  disabled: boolean
  pending: boolean
  onChange: (strategy: OrderStrategy) => void
}) {
  const { operation, order, disabled, pending, onChange } = props
  const options = orderStrategyOptions(operation, order)
  if (disabled && !pending) return <p className="text-[13px] text-[var(--muted)]">Order: {order.strategy === "custom" ? "Custom" : options.find((option) => option.value === order.strategy)?.label}</p>
  return (
    <div className="flex items-center gap-2" aria-busy={pending || undefined}>
      <span className="text-[13px] text-[var(--muted)]">Order by</span>
      <Select ariaLabel="Order by" align="end" value={order.strategy} options={options} disabled={disabled}
        renderValue={(value) => options.find((option) => option.value === value)?.label}
        onValueChange={(value) => {
          if (value === "free_first" || value === "lowest_cost" || value === "custom") onChange(value)
        }} />
    </div>
  )
}
