import React from "react"
import { Modal } from "@/components/common/Modal"
import { Button } from "@/components/ui/button"
import type { ProviderConfig } from "@/types/freesearch"
import { ModalDetail } from "./ModalDetail"
import {
  formatLatency,
  formatQuota,
  stripProtocol,
} from "./shared"
import type { TestResult } from "./shared"

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
          <ModalDetail label="Health" value={provider.circuitBreaker === "open" ? "open" : provider.healthStatus} />
          <ModalDetail label="p95" value={formatLatency(provider.latencyP95Ms)} />
          <ModalDetail label="Quota" value={formatQuota(provider)} />
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
