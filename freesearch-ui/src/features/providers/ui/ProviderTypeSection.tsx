import { useState } from "react"
import type { ProviderTypeView } from "@/domains/providers"
import { Button } from "@/shared/ui/button"
import { OperationTags } from "@/shared/ui/OperationTags"
import type { ProjectProvidersController } from "../model/useProjectProvidersController"
import { AddBindingForm } from "./AddBindingForm"
import { ProviderBindingsTable } from "./ProviderBindingsTable"
import { ProviderCredentialsTable } from "./ProviderCredentialsTable"

interface ProviderTypeSectionProps {
  provider: ProviderTypeView
  controller: ProjectProvidersController
  canConfigure: boolean
  canManagePrivate: boolean
}

/** One provider type of the project: system state, credentials and bindings. */
export function ProviderTypeSection(props: ProviderTypeSectionProps) {
  const { provider, controller, canConfigure, canManagePrivate } = props
  const [adding, setAdding] = useState(false)
  const pending = controller.bindingStatus.pending

  return (
    <section
      aria-label={`${provider.name} provider`}
      data-testid={`provider-type-${provider.providerType}`}
      className="space-y-3 rounded border border-[var(--border-subtle)] p-4"
    >
      <header className="flex flex-wrap items-center gap-3">
        <h2 className="text-[var(--text-strong)]">{provider.name}</h2>
        {provider.killSwitch && (
          <span className="rounded bg-[var(--status-danger)]/15 px-1.5 py-0.5 text-[11px] text-[var(--status-danger)]">
            Disabled by system
          </span>
        )}
        <span className="text-[12px] text-[var(--muted)]">Runs: <OperationTags operations={provider.effectiveOperations} /></span>
      </header>
      <p className="text-[12px] text-[var(--muted)]">
        Supports {provider.capability.join(", ") || "nothing"} · Allowed by system{" "}
        {provider.systemEnabledOperations.join(", ") || "none"}
      </p>
      <ProviderCredentialsTable
        name={provider.name}
        credentials={provider.credentials}
        credentialsById={controller.credentialsById}
        canManagePrivate={canManagePrivate}
        actions={controller.credentialActions}
      />
      <ProviderBindingsTable
        provider={provider}
        canConfigure={canConfigure}
        pending={pending}
        onToggle={(binding, operation, on) => void controller.toggleOperation(binding, operation, on)}
        onRemove={(binding) => void controller.removeBinding(binding)}
      />
      {canConfigure && !adding && (
        <Button variant="outline" disabled={provider.credentials.length === 0} onClick={() => setAdding(true)}>
          Add binding
        </Button>
      )}
      {canConfigure && adding && (
        <AddBindingForm
          idPrefix={`binding-${provider.providerType}`}
          credentials={provider.credentials}
          pending={pending}
          onSubmit={controller.addBinding}
          onCancel={() => setAdding(false)}
        />
      )}
    </section>
  )
}
