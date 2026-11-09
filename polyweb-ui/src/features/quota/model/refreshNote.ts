import { formatRelativeTime } from "@/shared/lib/formatTime"

interface RefreshState {
  syncNote: string | null
  updatedAt: number | null
  needsCredential: boolean
}

/**
 * The note beside Refresh. An update reads as a relative time ("Updated just
 * now"), and a missing-key reply never sits next to data the card already
 * shows, so the two never contradict each other.
 */
export function refreshNote(state: RefreshState, hasData: boolean, now: number = Date.now()): string | null {
  if (state.syncNote === null) return null
  if (state.needsCredential && hasData) return null
  if (state.updatedAt !== null) return "Updated " + formatRelativeTime(state.updatedAt, now)
  return state.syncNote
}
