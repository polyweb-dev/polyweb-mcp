import { Switch } from "@/shared/ui/Switch"
import { TableCell } from "@/shared/ui/table"
import type { ProviderConfig } from "@/domains/providers"
import { OperationControl } from "./ProviderOperationControl"

interface ProviderRegistryControlsProps {
  provider: ProviderConfig
  canEdit: boolean
  globalPending: boolean
  onToggleGlobal: (enabled: boolean) => void
  onToggleSearch: (enabled: boolean) => void
  onToggleFetch: (enabled: boolean) => void
}

/**
 * Search, fetch, and global routing cells of one registry row. A role without
 * control-edit access sees the stored values as read-only text.
 */
export function ProviderRegistryControls({
  provider,
  canEdit,
  globalPending,
  onToggleGlobal,
  onToggleSearch,
  onToggleFetch,
}: ProviderRegistryControlsProps) {
  return (
    <>
      <TableCell className="whitespace-nowrap px-3 py-2.5">
        <OperationControl
          label="Search"
          providerName={provider.name}
          supported={provider.capabilities.includes("search")}
          enabled={provider.searchEnabled}
          globallyDisabled={!provider.globalEnabled}
          canEdit={canEdit}
          onToggle={onToggleSearch}
        />
      </TableCell>
      <TableCell className="whitespace-nowrap px-3 py-2.5">
        <OperationControl
          label="Fetch"
          providerName={provider.name}
          supported={provider.capabilities.includes("fetch")}
          enabled={provider.fetchEnabled}
          globallyDisabled={!provider.globalEnabled}
          canEdit={canEdit}
          onToggle={onToggleFetch}
        />
      </TableCell>
      <TableCell className="whitespace-nowrap px-3 py-2.5">
        <span className="sr-only">Global</span>
        {canEdit ? (
          <Switch
            checked={provider.globalEnabled}
            onChange={onToggleGlobal}
            disabled={globalPending}
            ariaLabel={`${provider.name} global routing`}
          />
        ) : (
          <span className="text-[12px] text-[var(--muted)]" title="Read-only for your role">
            {provider.globalEnabled ? "On" : "Off"}
          </span>
        )}
      </TableCell>
    </>
  )
}
