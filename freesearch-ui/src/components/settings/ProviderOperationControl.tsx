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
  onToggle: (enabled: boolean) => void
}

export const OperationControl: React.FC<OperationControlProps> = ({
  label,
  providerName,
  supported,
  enabled,
  globallyDisabled,
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

  return (
    <div title="Session-only — backend has global enable only">
      <Switch
        checked={enabled}
        onChange={onToggle}
        disabled={globallyDisabled}
        ariaLabel={`${providerName} ${label.toLowerCase()} routing`}
      />
    </div>
  )
}
