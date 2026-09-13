import type { QuotaConfidence } from "@/domains/dashboard"
import { ConfidenceLabel } from "./ConfidenceLabel"

/** Quota source cell: confidence chip or the no-snapshot dash. */
export function QuotaSource({ confidence }: { confidence: QuotaConfidence | null }) {
  return (
    <span className="text-[13px] text-[var(--muted)]">
      {confidence ? (
        <ConfidenceLabel confidence={confidence} />
      ) : (
        <span title="No quota snapshot from the backend">—</span>
      )}
    </span>
  )
}
