import { providerIdentity } from "@/domains/providers"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"
import { usageProviderLabel } from "../model/usageView"

/** Provider cell of the usage tables: the catalog logo and name. */
export function UsageProviderCell({ provider }: { provider: string }) {
  const identity = providerIdentity(provider)
  return (
    <ProviderBadge
      providerId={identity.id}
      name={usageProviderLabel(provider)}
      className="text-[var(--text-strong)]"
      logoClassName="size-3.5"
    />
  )
}
