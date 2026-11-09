import { ConfirmDialog } from "@/shared/ui/ConfirmDialog"
import { ProviderDialogTitle } from "@/shared/ui/ProviderDialogTitle"
import { providerIdentity } from "../model/providerIdentity"

export function StopOperationConfirm({ provider, operation, remaining, pending, error, onClose, onConfirm }: {
  provider: string
  operation: "search" | "fetch"
  projectName: string
  remaining?: "search" | "fetch"
  pending: boolean
  error?: string | null
  onClose: () => void
  onConfirm: () => void
}) {
  const identity = providerIdentity(provider)
  const label = operation === "search" ? "Search" : "Fetch"
  const stays = remaining ? `. ${remaining === "search" ? "Search" : "Fetch"} stays on` : ""
  return <ConfirmDialog open title={<ProviderDialogTitle providerId={identity.id} title={`Stop ${identity.name} ${label}`} />}
    message={`${identity.name} leaves this project's ${label} order${stays}`}
    confirmLabel={`Stop ${label}`} pending={pending} error={error} onClose={onClose} onConfirm={onConfirm} />
}
