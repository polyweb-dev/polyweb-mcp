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
  if (!supported) {
    return (
      <Tooltip>
        <TooltipTrigger
          render={<span className="inline-flex cursor-not-allowed" />}
        >
          <Switch
            checked={false}
            onChange={() => {}}
            disabled
            ariaLabel={`${providerName} ${label.toLowerCase()} routing (not supported)`}
          />
        </TooltipTrigger>
        <TooltipContent>
          {providerName} does not support {label.toLowerCase()}
        </TooltipContent>
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
    <div>
      <Switch
        checked={enabled}
        onChange={onToggle}
        disabled={globallyDisabled || pending}
        ariaLabel={`${providerName} ${label.toLowerCase()} routing`}
      />
    </div>
  )
}
