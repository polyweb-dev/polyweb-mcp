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
    <div className="fs-panel overflow-x-auto">
      <table aria-label="Without capacity" className="fs-table">
        <tbody>
          {[...providers].sort((a, b) => a.name.localeCompare(b.name)).map((provider) => <tr key={provider.providerType} className="h-[60px]">
            <td><ProviderBadge providerId={providerIdentity(provider.providerType).id} name={provider.name} logoClassName="size-4" /></td>
            <td className="text-right">{isOwner
              ? <Button variant="outline" size="sm" aria-label={`Add capacity for ${provider.name}`} onClick={() => onAdd(provider.providerType)}>Add capacity</Button>
              : <span className="text-[var(--muted)]">The provider owner must add capacity</span>}</td>
          </tr>)}
        </tbody>
      </table>
    </div>
  </Section>
}
