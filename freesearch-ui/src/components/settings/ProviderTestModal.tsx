import React from "react"
import { Modal } from "@/shared/ui/Modal"
import { Button } from "@/shared/ui/button"
import { FormActions } from "@/shared/ui/FormActions"
import { ProviderLogo } from "@/shared/ui/ProviderLogo"
import { formatDateTime } from "@/shared/lib/formatTime"
import type { ProviderConfig } from "@/domains/providers"
import { ModalDetail } from "./ProviderTestModalDetail"
import { capabilityList, lastResultText, stripProtocol } from "./providerDisplay"
import type { TimedTestResult } from "./providerDisplay"

/**
 * Connection test of one provider: its endpoint and capabilities, the last
 * result from this page, and the Test action. Opening it never probes.
 */
export const ProviderTestModal: React.FC<{
  provider: ProviderConfig | null
  testing: boolean
  lastResult?: TimedTestResult
  /** Current time (epoch ms) for the relative "checked" text. */
  now: number
  onClose: () => void
  onTest: (id: string) => void
}> = ({ provider, testing, lastResult, now, onClose, onTest }) => (
  <Modal
    isOpen={provider !== null}
    onClose={onClose}
    title={provider ? <><ProviderLogo providerId={provider.id} name={provider.name} />Test {provider.name}</> : "Test provider"}
    maxWidth="lg"
  >
    {provider && (
      <>
        <dl className="grid grid-cols-[120px_minmax(0,1fr)] gap-x-4 gap-y-2 text-[13px]">
          <ModalDetail label="Endpoint" value={stripProtocol(provider.baseUrl)} mono />
          <ModalDetail label="Capabilities" value={capabilityList(provider.capabilities)} />
          <dt className="text-[var(--muted)]">Last test</dt>
          <dd className="text-[var(--text-strong)]" title={lastResult ? formatDateTime(new Date(lastResult.checkedAt).toISOString()) : undefined}>
            {lastResultText(lastResult, now)}
          </dd>
        </dl>
        <FormActions>
          <Button type="button" size="form" variant="outline" onClick={onClose}>
            Close
          </Button>
          <Button type="button" size="form" onClick={() => onTest(provider.id)} disabled={testing}>
            {testing ? "Testing..." : "Test"}
          </Button>
        </FormActions>
      </>
    )}
  </Modal>
)
