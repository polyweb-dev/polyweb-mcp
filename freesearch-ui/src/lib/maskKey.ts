const MASK_RUN = "••••••••"

/**
 * Derives the write-only masked fingerprint shown in the key vault. Keys
 * shorter than 8 characters are fully masked.
 */
export function formatMaskedKey(rawKey: string): string {
  const trimmed = rawKey.trim()
  if (trimmed.length < 8) return MASK_RUN
  return `${trimmed.slice(0, 4)}_${MASK_RUN}${trimmed.slice(-4)}`
}
