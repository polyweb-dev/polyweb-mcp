import React from "react"
import { RefreshCw } from "lucide-react"
import { Button } from "@/shared/ui/button"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"
import { Tag } from "@/shared/ui/Tag"
import {
  TableCell,
  TableRow,
} from "@/shared/ui/table"
import { FETCH_BIT, SEARCH_BIT, providerCallCost, type ProviderConfig } from "@/domains/providers"
import { stripProtocol } from "./providerDisplay"
import type { TimedTestResult } from "./providerDisplay"
import { HealthStatus } from "@/shared/ui/HealthStatus"
import { ProviderRegistryControls } from "./ProviderRegistryControls"

interface ProviderRegistryRowProps {
  provider: ProviderConfig
  testing: boolean
  /** The last connection test of this provider run from this page. */
  lastResult: TimedTestResult | undefined
  /** Current time (epoch ms) for relative health times. */
  now: number
  accessPending: boolean
  /** False for a role without control-edit access: read-only values only. */
  canEdit: boolean
  onToggleGlobal: (enabled: boolean) => void
  onToggleSearch: (enabled: boolean) => void
  onToggleFetch: (enabled: boolean) => void
  onOpenTest: () => void
}

const CELL = "whitespace-nowrap px-3 py-2.5"

function callCost(provider: ProviderConfig, operation: "search" | "fetch"): string {
  const bit = operation === "search" ? SEARCH_BIT : FETCH_BIT
  if ((provider.supportMask & bit) === 0) return "Not supported"
  const price = providerCallCost(provider, operation)
  const keyless = provider.keylessCallCostUsd?.[operation]
  return keyless != null && Number(keyless) === 0 && price !== "Free" ? `${price} with a key` : price
}

function renderIdentityCell(provider: ProviderConfig) {
  return (
    <TableCell className={CELL}>
      <div className="flex items-center gap-2">
        <ProviderBadge providerId={provider.id} name={provider.name} />
        {provider.isCustom && <Tag tone="accent">Custom</Tag>}
        {provider.capabilities.includes("keyless_tier") && <Tag>No key needed</Tag>}
      </div>
    </TableCell>
  )
}

type HealthCellProps = Pick<ProviderRegistryRowProps, "provider" | "canEdit" | "testing" | "lastResult" | "now" | "onOpenTest">

function renderHealthCell({ provider, canEdit, testing, lastResult, now, onOpenTest }: HealthCellProps) {
  return (
    <TableCell className={CELL}>
      <div className="flex items-center gap-2">
        <HealthStatus result={lastResult} testing={testing} now={now} health={provider.healthStatus} checkedAt={provider.healthCheckedAt ?? null} />
        {canEdit && (
          <Button
            variant="ghost"
            size="icon-sm"
            type="button"
            onClick={onOpenTest}
            disabled={testing}
            aria-label={`${provider.name} test connection`}
            title={`Test ${provider.name} connection`}
            className="text-[var(--muted)]"
          >
            <RefreshCw aria-hidden="true" className={`size-3.5 ${testing ? "animate-spin" : ""}`} />
          </Button>
        )}
      </div>
    </TableCell>
  )
}

/** One provider of the catalog, including its costs and system controls. */
export const ProviderRegistryRow: React.FC<ProviderRegistryRowProps> = ({
  provider,
  testing,
  lastResult,
  now,
  accessPending,
  canEdit,
  onToggleGlobal,
  onToggleSearch,
  onToggleFetch,
  onOpenTest,
}) => (
  <TableRow className="border-b border-[var(--border-subtle)] last:border-b-0 hover:bg-[var(--elevated)] transition-colors">
    {renderIdentityCell(provider)}
    <TableCell className={`max-w-[240px] ${CELL}`}>
      <span className="block truncate font-mono text-[12px] text-[var(--muted)]" title={provider.baseUrl}>
        {stripProtocol(provider.baseUrl)}
      </span>
    </TableCell>
    <TableCell className={CELL}>
      <div className="tabular-nums text-[12px] text-[var(--muted)]">
        {callCost(provider, "search") === "Free" && callCost(provider, "fetch") === "Free" ? <div>Free</div> : <>
          {(provider.supportMask & SEARCH_BIT) !== 0 && <div>Search: {callCost(provider, "search")}</div>}
          {(provider.supportMask & FETCH_BIT) !== 0 && <div>Fetch: {callCost(provider, "fetch")}</div>}
          {provider.capabilities.includes("keyless_tier") && <div>Free without a key</div>}
        </>}
      </div>
    </TableCell>
    {renderHealthCell({ provider, canEdit, testing, lastResult, now, onOpenTest })}
    <ProviderRegistryControls
      provider={provider}
      canEdit={canEdit}
      accessPending={accessPending}
      onToggleGlobal={onToggleGlobal}
      onToggleSearch={onToggleSearch}
      onToggleFetch={onToggleFetch}
    />
  </TableRow>
)
