import type { DragEvent, ReactNode } from "react"
import { providerCallCost, providerIdentity } from "@/domains/providers"
import type { ProviderTypeView, RouteEntry } from "@/domains/providers"
import type { OrderOperation, OrderProvider } from "@/domains/routing"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"
import { ReorderHandle } from "@/shared/ui/ReorderHandle"
import { Switch } from "@/shared/ui/Switch"
import { Tag } from "@/shared/ui/Tag"
import { CredentialKeyCell } from "./CredentialKeyCell"
import { KeyHealthCell } from "./KeyHealthCell"

export interface ProviderOrderRowProps {
  item: OrderProvider
  entry: RouteEntry | undefined
  provider?: ProviderTypeView
  operation: OrderOperation
  index: number
  count: number
  ranked: boolean
  canConfigure: boolean
  pending: boolean
  target: boolean
  dragging?: boolean
  canEditSystem?: boolean
  pool?: ReactNode
  menu?: ReactNode
  poolOperations?: readonly OrderOperation[]
  isOwner?: boolean
  usesPool?: boolean
  showOperation?: boolean
  onToggle: (enabled: boolean) => void
  onMove: (direction: "up" | "down") => void
  onDragStart: (event: DragEvent) => void
  onDragEnd: () => void
  onDragOver: (event: DragEvent) => void
  onDrop: (event: DragEvent) => void
}

function providerCell(props: ProviderOrderRowProps, enabled: boolean, opLabel: string) {
  const { item, entry, provider, operation, canEditSystem } = props
  const systemOff = provider && (provider.killSwitch || !provider.systemEnabledOperations.includes(operation))
  return (
    <td>
        <span className="flex items-center gap-2">
          <ProviderBadge providerId={providerIdentity(item.provider).id} name={providerIdentity(item.provider).name} logoClassName="size-4" />
          {item.keyless && <Tag>No key needed</Tag>}
          {entry?.provider.killSwitch && <Tag tone="warning">Disabled by system</Tag>}
        </span>
        {!enabled && <span className="block text-[12px] text-[var(--muted)]">
          Off for {opLabel}. {systemOff ? <>Off in system. {canEditSystem && <a className="text-[var(--signal)] underline" href="/system/providers">Turn on in System Providers</a>}</>
            : provider ? "Not available for this project" : "Provider status is not available"}
        </span>}
    </td>
  )
}

function poolCell(props: ProviderOrderRowProps) {
  if (props.item.keyless && !props.poolOperations) return "No pool needed"
  if (props.pool !== undefined) return props.pool
  if (props.entry === undefined) return "—"
  return <CredentialKeyCell providerType={props.entry.provider.providerType} credential={props.entry.credential} />
}

function operationCell(props: ProviderOrderRowProps, enabled: boolean, opLabel: string) {
  if (props.usesPool) {
    if (!props.poolOperations) return <span title={props.item.keyless && enabled ? "Always on: no key needed" : "No pool available"}><Switch checked={enabled} disabled ariaLabel={`Use ${props.item.name} for ${opLabel}`} onChange={props.onToggle} /></span>
    if (!props.isOwner) return <Switch checked={enabled} disabled ariaLabel={`Use ${props.item.name} for ${opLabel}`} onChange={props.onToggle} />
    return <Switch checked={props.poolOperations.includes(props.operation)} disabled={props.pending} ariaLabel={`Use ${props.item.name} for ${opLabel}`} onChange={props.onToggle} />
  }
  if (!props.entry) return "—"
  return <Switch checked={enabled} disabled={!props.canConfigure || props.pending} ariaLabel={`Use ${props.item.name} for ${opLabel}`} onChange={props.onToggle} />
}

function operationEnabled(props: ProviderOrderRowProps): boolean {
  if (props.provider) return props.provider.effectiveOperations.includes(props.operation)
  if (props.usesPool) return props.poolOperations?.includes(props.operation) ?? false
  return props.entry?.binding.enabledOperations.includes(props.operation) ?? false
}

export function ProviderOrderRow(props: ProviderOrderRowProps) {
  const { item, operation, index, count, canConfigure, pending, target, dragging } = props
  const opLabel = operation === "search" ? "Search" : "Fetch"
  const enabled = operationEnabled(props)
  return (
    <tr data-provider={item.provider} onDragOver={props.ranked ? props.onDragOver : undefined} onDrop={props.ranked ? props.onDrop : undefined}
      className={`h-[60px] ${dragging ? "relative bg-[var(--raised)] shadow-lg" : target ? "shadow-[inset_0_2px_0_var(--signal)]" : ""}`}>
      <td>{props.ranked ? <ReorderHandle label={item.name} rank={index + 1} count={count} canEdit={canConfigure}
        pending={pending} onMove={props.onMove} onDragStart={props.onDragStart} onDragEnd={props.onDragEnd} />
        : <span aria-label="Not in dispatch order" className="text-[var(--muted)]">—</span>}</td>
      {providerCell(props, enabled, opLabel)}
      <td>{poolCell(props)}</td>
      <td className="tabular-nums text-[var(--muted)]">{providerCallCost(props.provider, operation, item.keyless)}</td>
      <td><KeyHealthCell project health={props.provider?.healthStatus ?? null} checkedAt={props.provider?.healthCheckedAt ?? null} /></td>
      {props.showOperation !== false && <td>{operationCell(props, enabled, opLabel)}</td>}
      <td className="fs-cell-actions">{props.menu}</td>
    </tr>
  )
}
