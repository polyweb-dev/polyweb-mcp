import type { TraceDetail } from "@/domains/activity"
import { useClipboard } from "@/shared/clipboard/useClipboard"
import { Button } from "@/shared/ui/button"

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
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      onClick={() => void copy(JSON.stringify(trace, null, 2))}
    >
      {copied ? "Copied" : "Copy JSON"}
    </Button>
  )
}
