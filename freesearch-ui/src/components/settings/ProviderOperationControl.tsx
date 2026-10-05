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
  pending: boolean
  onToggle: (enabled: boolean) => void
}

export const OperationControl: React.FC<OperationControlProps> = ({
  label,
  providerName,
  supported,
  enabled,
  globallyDisabled,
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
