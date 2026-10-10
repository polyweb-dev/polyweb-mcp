import { Switch } from "@/shared/ui/Switch"
import { TableCell } from "@/shared/ui/table"
import type { ProviderConfig } from "@/domains/providers"
import { FETCH_BIT, GLOBAL_BIT, SEARCH_BIT } from "@/domains/providers"
import { OperationControl } from "./ProviderOperationControl"

interface ProviderRegistryControlsProps {
  provider: ProviderConfig
  canEdit: boolean
  accessPending: boolean
  onToggleGlobal: (enabled: boolean) => void
  onToggleSearch: (enabled: boolean) => void
  onToggleFetch: (enabled: boolean) => void
}

/**
 * Search, fetch, and global routing cells of one registry row. A role without
 * control-edit access sees the stored values as read-only text.
 * Pending disables all toggles; unsupported operations stay disabled via masks.
 */
export function ProviderRegistryControls({
  provider,
  canEdit,
  accessPending,
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
          supported={(provider.supportMask & SEARCH_BIT) !== 0}
          enabled={provider.searchEnabled}
          globallyDisabled={!provider.globalEnabled}
          canEdit={canEdit}
          pending={accessPending}
          onToggle={onToggleSearch}
        />
      </TableCell>
      <TableCell className="whitespace-nowrap px-3 py-2.5">
        <OperationControl
          label="Fetch"
          providerName={provider.name}
          supported={(provider.supportMask & FETCH_BIT) !== 0}
          enabled={provider.fetchEnabled}
          globallyDisabled={!provider.globalEnabled}
          canEdit={canEdit}
          pending={accessPending}
          onToggle={onToggleFetch}
        />
      </TableCell>
      <TableCell className="whitespace-nowrap px-3 py-2.5">
        <span className="sr-only">Global</span>
        {canEdit ? (
          <Switch
            checked={provider.globalEnabled}
            onChange={onToggleGlobal}
            disabled={accessPending || (provider.supportMask & GLOBAL_BIT) === 0}
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
