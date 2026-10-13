import React from "react"
import { Modal } from "@/shared/ui/Modal"
import { Button } from "@/shared/ui/button"
import type { ProviderConfig } from "@/domains/providers"
import { useFreeSearch } from "@/context/useFreeSearch"
import { ModalDetail } from "./ProviderTestModalDetail"
import { stripProtocol } from "./providerDisplay"

type TestResult = Awaited<ReturnType<ReturnType<typeof useFreeSearch>["testProviderConnection"]>>

export const ProviderTestModal: React.FC<{
  provider: ProviderConfig | null
  testing: boolean
  lastResult?: TestResult
  onClose: () => void
  onTest: (id: string) => void
}> = ({ provider, testing, lastResult, onClose, onTest }) => (
  <Modal
    isOpen={provider !== null}
    onClose={onClose}
    title={provider ? `Test ${provider.name}` : "Test provider"}
    subtitle="Inspect the current provider state before running a connection probe."
    maxWidth="lg"
  >
    {provider && (
      <div className="space-y-4">
        <dl className="grid grid-cols-[110px_minmax(0,1fr)] gap-x-4 gap-y-2 text-[13px]">
          <ModalDetail label="Endpoint" value={stripProtocol(provider.baseUrl)} mono />
          <ModalDetail label="Capabilities" value={provider.capabilities.join(", ")} />
          <ModalDetail
            label="Last result"
            value={lastResult ? `${lastResult.success ? "healthy" : lastResult.message} · ${lastResult.latencyMs}ms` : "Not tested"}
          />
        </dl>
        <div className="flex justify-end border-t border-[var(--border-subtle)] pt-4">
          <Button type="button" onClick={() => onTest(provider.id)} disabled={testing}>
            {testing ? "Testing..." : "Test"}
          </Button>
        </div>
      </div>
    )}
  </Modal>
)
