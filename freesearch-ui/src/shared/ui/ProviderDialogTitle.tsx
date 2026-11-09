import { ProviderLogo } from "./ProviderLogo"

/** Provider identity in a dialog heading; the parent supplies heading semantics. */
export function ProviderDialogTitle({ providerId, providerName, action }: {
  providerId: string
  providerName: string
  action: string
}) {
  return <span className="inline-flex min-w-0 items-center gap-2">
    <ProviderLogo providerId={providerId} name={providerName} />
    <span>{action} for {providerName}</span>
  </span>
}
