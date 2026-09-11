import type { QuotaConfidence } from "@/types/freesearch"

/** Confidence chip with its vendor/observed/estimated explanation. */
export function ConfidenceLabel({ confidence }: { confidence: QuotaConfidence }) {
  return (
    <span
      className="text-[12px] capitalize text-[var(--muted)]"
      title={
        confidence === "authoritative"
          ? "Polled directly from the vendor"
          : confidence === "observed"
            ? "Observed from vendor response headers or local counters"
            : "Estimated locally; not a vendor balance"
      }
    >
      {confidence}
    </span>
  )
}
