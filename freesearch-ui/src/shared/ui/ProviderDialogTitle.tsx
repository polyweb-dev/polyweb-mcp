import { ProviderLogo } from "./ProviderLogo"

/** Provider identity in a dialog heading; the parent supplies heading semantics. */
export function ProviderDialogTitle({ providerId, title }: { providerId: string; title: string }) {
  return <span className="inline-flex min-w-0 items-center gap-2">
    <ProviderLogo providerId={providerId} name={title} />
    <span>{title}</span>
  </span>
}
