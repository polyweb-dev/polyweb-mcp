import React from "react"
import { Switch } from "@/shared/ui/Switch"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/shared/ui/tooltip"

interface OperationControlProps {
  label: "Search" | "Fetch"
  providerName: string
  supported: boolean
  enabled: boolean
  globallyDisabled: boolean
  /** False for a role without control-edit access: show the value only. */
  canEdit: boolean
  pending: boolean
  onToggle: (enabled: boolean) => void
}

/**
 * One operation cell of a registry row. An operation the provider cannot run
 * reads as unavailable (a dash with a "Not supported" tooltip), never as a
 * disabled switch; a role without edit access sees On or Off.
 */
export const OperationControl: React.FC<OperationControlProps> = ({
  label,
  providerName,
  supported,
  enabled,
  globallyDisabled,
  canEdit,
  pending,
  onToggle,
}) => {
  const operation = label.toLowerCase()
  if (!supported) {
    return (
      <Tooltip>
        <TooltipTrigger render={<span className="inline-flex h-5 w-9 items-center text-[var(--muted)]" />}>
          <span aria-hidden="true">—</span>
          <span className="sr-only">{`${providerName} does not support ${operation}`}</span>
        </TooltipTrigger>
        <TooltipContent>Not supported</TooltipContent>
      </Tooltip>
    )
  }

  if (!canEdit) {
    return (
      <span
        className="text-[12px] text-[var(--muted)]"
        title="Read-only for your role"
      >
        {enabled ? "On" : "Off"}
      </span>
    )
  }

  return (
    <Switch
      checked={enabled}
      onChange={onToggle}
      disabled={globallyDisabled || pending}
      ariaLabel={`${providerName} ${operation} routing`}
    />
  )
}
