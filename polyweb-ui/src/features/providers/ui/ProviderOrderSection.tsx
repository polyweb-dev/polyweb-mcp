import { useSearchParams } from "react-router"
import { providerTypeName } from "@/domains/providers"
import type { ProviderTypeView } from "@/domains/providers"
import type { OrderOperation, OrderStrategy, ProjectOrder } from "@/domains/routing"
import { reorderProviderPriority } from "@/shared/lib/reorderProviderPriority"
import { Button } from "@/shared/ui/button"
import { EmptyState } from "@/shared/ui/EmptyState"
import { PillTabs } from "@/shared/ui/PillTabs"
import { PillTabsPanel } from "@/shared/ui/PillTabsPanel"
import { Section } from "@/shared/ui/Section"
import { Switch } from "@/shared/ui/Switch"
import { Tag } from "@/shared/ui/Tag"
import { TabsList, TabsTrigger } from "@/shared/ui/tabs"
import { useProviderOrder } from "../model/useProviderOrder"
import type { ProviderOrderContext } from "../model/providerOrderContext"
import { ProviderOrderRows } from "./ProviderOrderRows"
import { ProviderOrderToolbar } from "./ProviderOrderToolbar"

export type { ProviderOrderContext } from "../model/providerOrderContext"

function nameOf(id: string, providers: readonly ProviderTypeView[]): string {
  return providers.find((provider) => provider.providerType === id)?.name ?? providerTypeName(id)
}

function showOperationColumn(context: ProviderOrderContext, data: ProjectOrder): boolean {
  if (context.isOwner || (!context.poolOperations && context.canConfigure)) return true
  return (["search", "fetch"] as const).some((operation) => data[operation].providers.some((item) => {
    const provider = context.providers.find((provider) => provider.providerType === item.provider)
    return provider !== undefined && !provider.effectiveOperations.includes(operation)
  }))
}

function notAllowed(ids: string[], context: ProviderOrderContext, operation: OrderOperation) {
  if (ids.length === 0) return null
  if (context.poolOperations) {
    const pools = ids.filter((id) => context.poolOperations?.(id))
    if (pools.length === 0) return null
    return <div className="space-y-2"><p className="text-[13px] text-[var(--muted)]">Not in this order:</p>
      {pools.map((id) => <div key={id} className="flex items-center gap-3">
        <span>{nameOf(id, context.providers)}</span>
        {context.isOwner ? <Switch checked={false} disabled={context.operationPending} ariaLabel={`Use ${nameOf(id, context.providers)} for ${operation === "search" ? "Search" : "Fetch"}`}
          onChange={(enabled) => context.changePoolOperation?.(id, operation, enabled)} /> : <Tag>Off</Tag>}
      </div>)}
    </div>
  }
  const names = ids.map((id) => nameOf(id, context.providers)).join(", ")
  return <p className="text-[13px] text-[var(--muted)]">Not in this list: {names}. {ids.length === 1 ? "Its pool does" : "Their pools do"} not allow {operation === "search" ? "Search" : "Fetch"}</p>
}

/** Self-contained R3 section; the vault lane supplies owner and pool slots through context. */
export function ProviderOrderSection({ context }: { context: ProviderOrderContext }) {
  const { projectId, canConfigure } = context
  const [searchParams, setSearchParams] = useSearchParams()
  const operation: OrderOperation = searchParams.get("operation") === "fetch" ? "fetch" : "search"
  const orderState = useProviderOrder(projectId, context.revision)
  const { state, pending, undo, save } = orderState
  if (state.status === "loading") return <p role="status">Loading the order…</p>
  if (state.status === "error") return <div role="alert"><p>Cannot load the provider order</p><Button variant="outline" size="form" onClick={() => void orderState.reload()}>Retry</Button></div>
  const data = state.data
  const order = data[operation]
  const opLabel = operation === "search" ? "Search" : "Fetch"
  const canServe = order.providers.some((item) =>
    context.providers.find((provider) => provider.providerType === item.provider)?.effectiveOperations.includes(operation))
  const change = (strategy: OrderStrategy) => {
    if (strategy !== order.strategy) void save(operation, { strategy }, order.strategy)
  }
  const move = async (source: string, target: string) => {
    const ids = order.providers.map((item) => item.provider)
    const next = reorderProviderPriority(ids, source, target)
    if (ids.join("|") !== next.join("|")) await save(operation, { strategy: "custom", order: next }, null)
  }
  return (
    <Section title="Provider order" className="[&>div:first-child]:min-h-0">
      <PillTabs ariaLabel="Provider order operations" idPrefix="provider-order" value={operation}
        onValueChange={(value) => {
          if (value !== "search" && value !== "fetch") return
          setSearchParams((previous) => {
            const next = new URLSearchParams(previous)
            next.set("operation", value)
            return next
          }, { replace: true })
        }}
        options={[{ value: "search", label: `Search ${data.search.providers.length}` }, { value: "fetch", label: `Fetch ${data.fetch.providers.length}` }]}>
        <div className="flex items-center justify-between gap-4">
          <TabsList variant="pill" aria-label="Provider order operations">
            {(["search", "fetch"] as const).map((tab) => <TabsTrigger key={tab} value={tab}
              id={`provider-order-tab-${tab}`} aria-controls={`provider-order-panel-${tab}`}>
              {tab === "search" ? "Search" : "Fetch"}{" "}
              <span className="rounded bg-[var(--raised)] px-1 tabular-nums text-[var(--muted)]">{data[tab].providers.length}</span>
            </TabsTrigger>)}
          </TabsList>
          <div className="flex h-8 items-center gap-3">
            {undo?.operation === operation && <Button variant="outline" size="sm" disabled={pending} onClick={() => void save(operation, { strategy: undo.strategy }, null)}>Undo</Button>}
            {order.providers.length > 0 && <ProviderOrderToolbar operation={operation} order={order} disabled={!canConfigure || pending} pending={pending} onChange={change} />}
          </div>
        </div>
        {(["search", "fetch"] as const).map((tab) => <PillTabsPanel key={tab} value={tab}>
          <div className="space-y-3 pt-3">
            {!canServe && <div role="status" className="flex items-center justify-between gap-3 rounded border border-[var(--border-subtle)] bg-[var(--raised)] px-3 py-2 text-[13px]">
              <span>No provider can serve {opLabel} in this project</span>
              {context.isOwner && context.addCapacity && <Button variant="outline" size="sm" onClick={context.addCapacity}>Add capacity</Button>}
            </div>}
            {order.providers.length === 0 ? <EmptyState title={`No provider serves ${opLabel}`}
              description={<>No pool of this project allows {opLabel}{!context.isOwner && `. Ask ${context.ownerContact ?? "the provider owner"} to allow ${opLabel} in a pool`}</>}
              action={context.isOwner ? <a href="/account/keys" className="text-[var(--signal)]">Change pools</a> : undefined} /> : <>
              <div className="flex justify-between gap-4 text-[13px] text-[var(--muted)]">
                <p>Calls use providers from top to bottom. Unhealthy providers move to the end</p>
              </div>
              <ProviderOrderRows key={operation} context={context} order={order} operation={operation} pending={pending} move={move} showOperation={showOperationColumn(context, data)} />
            </>}
            {notAllowed(order.notAllowed, context, operation)}
          </div>
        </PillTabsPanel>)}
      </PillTabs>
    </Section>
  )
}
