import { providerIdentity } from "@/domains/providers"
import type { OrderProvider, ProjectOrder } from "@/domains/routing"
import type { ScopedResourceState } from "@/shared/lib/useScopedResource"
import { ProviderLogo } from "@/shared/ui/ProviderLogo"
import { Section } from "@/shared/ui/Section"
import { SectionLink } from "./SectionLink"

/**
 * The first providers in each operation order, as returned by the project API.
 */
function orderList(label: string, providers: readonly OrderProvider[], destination: string) {
  return (
    <div>
      <h4 className="mb-2 text-[13px] font-medium text-[var(--text-strong)]">{label}</h4>
      {providers.length === 0 ? <p className="text-[13px] text-[var(--muted)]">No providers</p> : (
        <ol aria-label={label} className="fs-panel divide-y divide-[var(--hairline)]">
          {providers.slice(0, 3).map((provider, index) => {
            const identity = providerIdentity(provider.provider)
            return (
              <li key={provider.provider} className="flex items-center gap-3 px-4 py-2 text-[13px]">
                <span className="tnum text-[var(--muted)]"><span className="sr-only">Rank </span>{index + 1}</span>
                <ProviderLogo providerId={identity.id} name={identity.name} />
                <span className="min-w-0 truncate font-medium text-[var(--text-strong)]">{identity.name}</span>
              </li>
            )
          })}
        </ol>
      )}
      {providers.length > 3 && <div className="mt-2 text-[12px]"><SectionLink to={destination} aria-label={`View ${label.toLowerCase()}`}>+{providers.length - 3} more</SectionLink></div>}
    </div>
  )
}

export function OverviewRouteOrder({
  projectId,
  order,
  canConfigure,
}: {
  projectId: string
  order: ScopedResourceState<ProjectOrder>
  canConfigure: boolean
}) {
  return (
    <Section
      title="Provider order"
      actions={
        <SectionLink to={`/p/${projectId}/providers`}>
          {canConfigure ? "Manage providers" : "View providers"}
        </SectionLink>
      }
    >
      {order.status === "loading" && <p role="status" className="text-[13px] text-[var(--muted)]">Loading provider order…</p>}
      {order.status === "error" && <p role="alert" className="text-[13px] text-[var(--muted)]">The provider order did not load</p>}
      {order.status === "ready" && <div className="space-y-4">
        {orderList("Search order", order.data.search.providers, `/p/${projectId}/providers?operation=search`)}
        {orderList("Fetch order", order.data.fetch.providers, `/p/${projectId}/providers?operation=fetch`)}
      </div>}
    </Section>
  )
}
