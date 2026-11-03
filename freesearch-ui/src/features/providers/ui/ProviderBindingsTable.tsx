import { CREDENTIAL_OPERATIONS } from "@/domains/providers"
import type { ProviderBinding, ProviderOperation, ProviderTypeView } from "@/domains/providers"
import { Button } from "@/shared/ui/button"
import { Switch } from "@/shared/ui/Switch"
import { CELL_CLASS, HEAD_CLASS } from "./formStyles"

const COLUMNS = ["Route label", "Credential", "Priority", "Search", "Fetch", "Effective"]

interface ProviderBindingsTableProps {
  provider: ProviderTypeView
  canConfigure: boolean
  pending: boolean
  onToggle: (binding: ProviderBinding, operation: ProviderOperation, on: boolean) => void
  onRemove: (binding: ProviderBinding) => void
}

/** Bindings of one provider type with per-operation toggles. */
export function ProviderBindingsTable(props: ProviderBindingsTableProps) {
  const { provider, canConfigure, pending, onToggle, onRemove } = props
  const labels = new Map(provider.credentials.map((credential) => [credential.id, credential.label]))
  return (
    <table aria-label={`${provider.name} bindings`} className="w-full text-left text-[13px]">
      <thead>
        <tr className="border-b border-[var(--border-subtle)] text-[var(--muted)]">
          {COLUMNS.map((column) => (
            <th key={column} scope="col" className={HEAD_CLASS}>
              {column}
            </th>
          ))}
          <th scope="col" className={HEAD_CLASS}>
            <span className="sr-only">Actions</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {provider.bindings.length === 0 && (
          <tr>
            <td colSpan={COLUMNS.length + 1} className="py-3 text-[var(--muted)]">
              No bindings yet.
            </td>
          </tr>
        )}
        {provider.bindings.map((binding) => (
          <tr key={binding.id} className="border-b border-[var(--border-subtle)] text-[var(--text)]">
            <td className={CELL_CLASS}>{binding.routeLabel}</td>
            <td className={CELL_CLASS}>{labels.get(binding.credentialId) ?? binding.credentialId}</td>
            <td className={`${CELL_CLASS} tnum`}>{binding.priority}</td>
            {CREDENTIAL_OPERATIONS.map((operation) => (
              <td key={operation} className={CELL_CLASS}>
                <Switch
                  checked={binding.enabledOperations.includes(operation)}
                  disabled={!canConfigure || pending || !provider.capability.includes(operation)}
                  ariaLabel={`Enable ${operation} for ${binding.routeLabel}`}
                  onChange={(on) => onToggle(binding, operation, on)}
                />
              </td>
            ))}
            <td className={CELL_CLASS}>{binding.effectiveOperations.join(", ") || "none"}</td>
            <td className="py-2 align-top">
              {canConfigure && (
                <Button
                  size="sm"
                  variant="destructive"
                  aria-label={`Remove binding ${binding.routeLabel}`}
                  disabled={pending}
                  onClick={() => onRemove(binding)}
                >
                  Remove
                </Button>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
