import { useState } from "react"
import type { SearchResult } from "@/domains/execution"
import { useClipboard } from "@/shared/clipboard/useClipboard"

export interface ResultPreview {
  selectedResultForPreview: SearchResult | null
  copied: boolean
  setSelectedResultForPreview: (value: SearchResult | null) => void
  copyToClipboard: (text: string) => void
}

/**
 * Inspector selection and clipboard state for playground results. The copied
 * flag clears on the same 2s timer as the monolith so polite/live regions
 * announce identical copy feedback.
 */
export function useResultPreview(): ResultPreview {
  const [selectedResultForPreview, setSelectedResultForPreview] = useState<SearchResult | null>(null)
  // Transient 2s feedback with the legacy fire-and-forget quirk preserved:
  // copied is unconditional and the write promise floats (see optimistic).
  const clipboard = useClipboard({ resetAfterMs: 2000, optimistic: true })

  const copyToClipboard = (text: string) => {
    void clipboard.copy(text)
  }

  return {
    selectedResultForPreview,
    copied: clipboard.copied,
    setSelectedResultForPreview,
    copyToClipboard,
  }
}
