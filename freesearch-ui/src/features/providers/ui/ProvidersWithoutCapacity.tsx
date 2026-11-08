import { providerIdentity } from "@/domains/providers"
import type { ProviderTypeView } from "@/domains/providers"
import { Button } from "@/shared/ui/button"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"
import { Section } from "@/shared/ui/Section"

export function ProvidersWithoutCapacity({ providers, isOwner, onAdd }: {
  providers: readonly ProviderTypeView[]
  isOwner: boolean
  onAdd: (provider: string) => void
}) {
  if (providers.length === 0) return null
  return <Section title="Without capacity">
    <ul aria-label="Without capacity" className="fs-panel divide-y divide-[var(--border-subtle)]">
      {[...providers].sort((a, b) => a.name.localeCompare(b.name)).map((provider) => <li key={provider.providerType} className="flex min-h-12 items-center justify-between gap-4 px-4 py-2">
        <ProviderBadge providerId={providerIdentity(provider.providerType).id} name={provider.name} logoClassName="size-4" />
        {isOwner
          ? <Button variant="secondary" className="w-28" aria-label={`Add capacity for ${provider.name}`} onClick={() => onAdd(provider.providerType)}>Add capacity</Button>
          : <span className="text-[var(--muted)]">The provider owner must add capacity</span>}
      </li>)}
    </ul>
  </Section>
}
