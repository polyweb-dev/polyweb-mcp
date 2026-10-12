import React from "react"
import { RefreshCw } from "lucide-react"
import { ProviderLogo } from "@/components/common/ProviderLogo"
import { Button } from "@/shared/ui/button"
import {
  TableCell,
  TableRow,
} from "@/shared/ui/table"
import type { ProviderConfig } from "@/domains/providers"
import { stripProtocol } from "./providerDisplay"
import { PriorityIndicator } from "./ProviderPriorityControl"
import { ProviderRegistryControls } from "./ProviderRegistryControls"
import { RowPill } from "./ProviderRowPill"

interface ProviderRegistryRowProps {
  provider: ProviderConfig
  rank: number
  providerCount: number
  testing: boolean
  accessPending: boolean
  canMoveUp: boolean
  canMoveDown: boolean
  /** False for a role without control-edit access: read-only values only. */
  canEdit: boolean
  isDragging?: boolean
  isDragOver?: boolean
  onDragStart?: (e: React.DragEvent) => void
  onDragOver?: (e: React.DragEvent) => void
  onDrop?: (e: React.DragEvent) => void
  onDragEnd?: () => void
  onMovePriority: (direction: "up" | "down") => void
  onToggleGlobal: (enabled: boolean) => void
  onToggleSearch: (enabled: boolean) => void
  onToggleFetch: (enabled: boolean) => void
  onOpenTest: () => void
}

function getRowClassName(isDragging: boolean, isDragOver: boolean): string {
  let cls = "border-b border-[var(--border-subtle)] last:border-b-0 hover:bg-[var(--elevated)] transition-colors"
  if (isDragging) cls += " opacity-40 bg-[var(--elevated)]"
  if (isDragOver) cls += " border-t-2 border-t-[var(--signal)] bg-[var(--elevated)]"
  return cls
}

function renderIdentityCell(provider: ProviderConfig) {
  return (
    <TableCell className="whitespace-nowrap px-3 py-2.5">
      <div className="flex items-center gap-2">
        <ProviderLogo providerId={provider.id} />
        <span className="font-medium text-[var(--text-strong)]">{provider.name}</span>
        {provider.isCustom && <RowPill tone="signal">custom</RowPill>}
        {provider.capabilities.includes("keyless_tier") && (
          <RowPill tone="healthy">keyless</RowPill>
        )}
      </div>
    </TableCell>
  )
}

function renderTestCell(
  provider: ProviderConfig,
  canEdit: boolean,
  testing: boolean,
  onOpenTest: () => void,
) {
  return (
    <TableCell className="whitespace-nowrap px-3 py-2.5">
      {canEdit ? (
        <Button
          variant="ghost"
          size="icon-sm"
          type="button"
          onClick={onOpenTest}
          disabled={testing}
          aria-label={`${provider.name} test connection`}
          title={`Test ${provider.name} connection`}
        >
          <RefreshCw aria-hidden="true" className={`size-3.5 ${testing ? "animate-spin" : ""}`} />
        </Button>
      ) : (
        <span className="text-[12px] text-[var(--muted)]" title="Read-only for your role">
          Hidden
        </span>
      )}
    </TableCell>
  )
}

export const ProviderRegistryRow: React.FC<ProviderRegistryRowProps> = ({
  provider,
  rank,
  providerCount,
  testing,
  accessPending,
  canMoveUp,
  canMoveDown,
  canEdit,
  isDragging = false,
  isDragOver = false,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
  onMovePriority,
  onToggleGlobal,
  onToggleSearch,
  onToggleFetch,
  onOpenTest,
}) => {
  const handleDragStart = (e: React.DragEvent) => {
    if ((e.target as HTMLElement).closest("button, input, [role='switch']")) {
      e.preventDefault()
      return
    }
    onDragStart?.(e)
  }

  return (
    <TableRow
      draggable={canEdit}
      onDragStart={canEdit ? handleDragStart : undefined}
      onDragOver={canEdit ? onDragOver : undefined}
      onDrop={canEdit ? onDrop : undefined}
      onDragEnd={canEdit ? onDragEnd : undefined}
      className={getRowClassName(isDragging, isDragOver)}
    >
      <TableCell className="w-24 whitespace-nowrap px-3 py-2.5">
        <PriorityIndicator
          provider={provider}
          rank={rank}
          providerCount={providerCount}
          canMoveUp={canMoveUp}
          canMoveDown={canMoveDown}
          canEdit={canEdit}
          onMovePriority={onMovePriority}
        />
      </TableCell>
      {renderIdentityCell(provider)}
      <TableCell className="max-w-[250px] whitespace-nowrap px-3 py-2.5">
        <span className="block truncate font-mono text-[12px] text-[var(--muted)]" title={provider.baseUrl}>
          {stripProtocol(provider.baseUrl)}
        </span>
      </TableCell>
      {renderTestCell(provider, canEdit, testing, onOpenTest)}
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
}
