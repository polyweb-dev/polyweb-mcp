import type { OrderOperation, OperationOrder } from "@/domains/routing"
import type { SelectOption } from "@/shared/ui/select"

export function orderStrategyOptions(_operation: OrderOperation, order: OperationOrder): SelectOption[] {
  return [
    { value: "free_first", label: "Free first" },
    { value: "lowest_cost", label: "Lowest cost" },
    {
      value: "custom", label: "Custom order", disabled: !order.hasSavedCustom && order.strategy !== "custom",
    },
  ]
}
