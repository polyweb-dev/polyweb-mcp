import type { AvailableCredential, ProviderTypeView } from "@/domains/providers"
import type { RowAction } from "@/shared/ui/RowActionsMenu"
import { isKeylessCredential } from "../model/credentialDisplay"
import type { ProjectProvidersController } from "../model/useProjectProvidersController"

export interface KeyMenuInput {
  provider: ProviderTypeView
  credential: AvailableCredential
  controller: ProjectProvidersController
  canManagePrivate: boolean
}

/**
 * Key items of a row menu, for keys this project may manage: Connect and
 * Disconnect for OAuth, Rotate key for API keys (not for a keyless tier),
 * then Delete key ("Remove from project" for a keyless tier). Delete and
 * Disconnect confirm in the shared key dialogs.
 */
export function keyMenuActions({ provider, credential, controller, canManagePrivate }: KeyMenuInput): RowAction[] {
  const managed = controller.credentialsById.get(credential.id)
  if (!canManagePrivate || managed?.canManage !== true) return []
  const ref = { id: credential.id, label: credential.label, generation: managed.generation }
  const { credentialActions } = controller
  const keyless = isKeylessCredential(provider.providerType, credential)
  const actions: RowAction[] = []
  if (credential.authMode === "oauth") {
    actions.push({ key: "connect", label: "Connect", onSelect: () => credentialActions.openConnect(ref) })
    actions.push({ key: "disconnect", label: "Disconnect", onSelect: () => credentialActions.requestDisconnect(ref) })
  } else if (!keyless) {
    actions.push({ key: "rotate", label: "Rotate key", onSelect: () => credentialActions.openRotate(ref) })
  }
  actions.push({
    key: "delete",
    label: keyless ? "Remove from project" : "Delete key",
    danger: true,
    onSelect: () => credentialActions.requestDelete(ref),
  })
  return actions
}
