import { Check, Copy } from "lucide-react"
import type { TraceDetail } from "@/domains/activity"
import { useClipboard } from "@/shared/clipboard/useClipboard"
import { Button } from "@/shared/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/shared/ui/tooltip"

export interface TraceCopyJsonButtonProps {
  trace: TraceDetail
}

/**
 * Copies the decoded trace detail as pretty-printed JSON, exactly as stored:
 * a metadata-only trace copies its null input and output. "Copied" shows only
 * after the clipboard write succeeds, then clears after 2 s.
 */
export function TraceCopyJsonButton({ trace }: TraceCopyJsonButtonProps) {
  const { copied, copy } = useClipboard({ resetAfterMs: 2000 })
  const label = copied ? "Copied" : "Copy JSON"
  const Icon = copied ? Check : Copy
  return (
    <Tooltip>
      <TooltipTrigger
        closeOnClick={false}
        render={
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label={label}
            onClick={() => void copy(JSON.stringify(trace, null, 2))}
          />
        }
      >
        <Icon aria-hidden="true" />
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  )
}
