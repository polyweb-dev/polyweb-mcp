import type { ReactNode } from "react"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { useProjects } from "@/domains/projects"
import { canEditControls, canReadControls } from "./permissions"

/**
 * Control-plane composition of one account.
 *
 * The capability flags come from the live system access descriptor, so a
 * caller without `system.settings.read` makes no control read and one without
 * `system.settings.write` gets no edit affordance. While the descriptor loads
 * both flags stay off; the domain providers start their reads once it grants
 * them. The account UUID keys the composition, so an account switch remounts
 * it.
 */
export function WorkspaceControls({
  accountId,
  children,
}: {
  accountId: string
  children: ReactNode
}) {
  const { systemAccess } = useProjects()
  return (
    <FreeSearchProvider
      key={accountId}
      accountId={accountId}
      canReadControls={canReadControls(systemAccess)}
      canEditControls={canEditControls(systemAccess)}
    >
      {children}
    </FreeSearchProvider>
  )
}
