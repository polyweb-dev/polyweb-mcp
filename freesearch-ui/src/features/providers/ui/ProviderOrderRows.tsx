import type { OrderOperation, OrderProvider, OperationOrder } from "@/domains/routing"
import { useDragReorder } from "@/shared/lib/useDragReorder"
import { useFlipReorder } from "@/shared/ui/useFlipReorder"
import { ProviderOrderRow } from "./ProviderOrderRow"
import type { ProviderOrderContext } from "../model/providerOrderContext"

export function ProviderOrderRows(props: {
  context: ProviderOrderContext
  order: OperationOrder
  operation: OrderOperation
  pending: boolean
  showOperation: boolean
  move: (source: string, target: string) => Promise<void>
}) {
  const { context, order, operation, pending, move, showOperation } = props
  const drag = useDragReorder(move)
  const isEnabled = (item: OrderProvider) => {
    const provider = context.providers.find((entry) => entry.providerType === item.provider)
    return provider ? provider.effectiveOperations.includes(operation) : true
  }
  const enabled = order.providers.filter(isEnabled)
  const disabled = order.providers.filter((item) => !isEnabled(item))
  const displayed = [...enabled, ...disabled]
  const tbody = useFlipReorder(displayed.map((item) => item.provider).join("|"))
  return (
    <div className="fs-panel overflow-x-auto" onDragLeave={drag.leaveList}>
      <table aria-label={`${operation === "search" ? "Search" : "Fetch"} provider order`} className="fs-table table-fixed min-w-[1080px]">
        <colgroup>
          <col className="w-[144px]" /><col className="w-[240px]" /><col />
          <col className="w-[144px]" /><col className="w-[144px]" />
          {showOperation && <col className="w-[96px]" />}<col className="w-[44px]" />
        </colgroup>
        <thead><tr>
          <th scope="col">Order</th><th scope="col">Provider</th><th scope="col">Pool</th>
          <th scope="col" title={`Catalog price for one ${operation} with this access mode`}>Cost per call</th>
          <th scope="col">Health</th>{showOperation && <th scope="col">On</th>}<th scope="col"><span className="sr-only">Actions</span></th>
        </tr></thead>
        <tbody ref={tbody}>
          {displayed.map((item, index) => {
            return <ProviderOrderRow key={item.provider} item={item} provider={context.providers.find((provider) => provider.providerType === item.provider)} operation={operation} index={index}
              count={enabled.length} ranked={index < enabled.length} canConfigure={context.canConfigure} pending={pending || Boolean(context.operationPending)}
              target={drag.targetId === item.provider} dragging={drag.draggingId === item.provider} canEditSystem={context.canEditSystem} pool={context.renderPool?.(item, operation)} menu={context.renderMenu?.(item)}
              poolOperations={context.poolOperations?.(item.provider)} isOwner={context.isOwner} showOperation={showOperation}
              onToggle={(enabled) => context.changePoolOperation?.(item.provider, operation, enabled)}
              onMove={(direction) => { const target = enabled[index + (direction === "up" ? -1 : 1)]; if (target) void move(item.provider, target.provider) }}
              onDragStart={(event) => drag.startDrag(item.provider, event)} onDragEnd={drag.clearDrag}
              onDragOver={(event) => drag.dragOver(item.provider, event)} onDrop={(event) => drag.drop(item.provider, event)} />
          })}
        </tbody>
      </table>
    </div>
  )
}
