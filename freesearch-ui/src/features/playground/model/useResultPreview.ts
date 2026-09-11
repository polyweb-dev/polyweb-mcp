import { useState } from "react"
import type { SearchResult } from "@/types/freesearch"

export interface ResultPreview {
  selectedResultForPreview: SearchResult | null
  showJsonInspector: boolean
  copied: boolean
  setSelectedResultForPreview: (value: SearchResult | null) => void
  setShowJsonInspector: (value: boolean | ((previous: boolean) => boolean)) => void
  copyToClipboard: (text: string) => void
}

/**
 * Inspector selection and clipboard state for playground results. The copied
 * flag clears on the same 2s timer as the monolith so polite/live regions
 * announce identical copy feedback.
 */
export function useResultPreview(): ResultPreview {
  const [selectedResultForPreview, setSelectedResultForPreview] = useState<SearchResult | null>(null)
  const [showJsonInspector, setShowJsonInspector] = useState(false)
  const [copied, setCopied] = useState(false)

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return {
    selectedResultForPreview,
    showJsonInspector,
    copied,
    setSelectedResultForPreview,
    setShowJsonInspector,
    copyToClipboard,
  }
}
