/**
 * One date and time format for every table and list: `Nov 2, 12:55 PM` for
 * an event, `Nov 2, 2026` for a calendar date. Unparseable input comes back
 * unchanged, so a bad timestamp is visible rather than hidden.
 */
export function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  })
}

/** Calendar date of one timestamp, such as `Nov 2, 2026`. */
export function formatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })
}

/** Latency in whole milliseconds with a thousands separator and a space: `1,531 ms`. */
export function formatLatency(milliseconds: number): string {
  return `${Math.round(milliseconds).toLocaleString("en-US")} ms`
}

/** One past moment (epoch ms) relative to `now`: `just now`, `2 min ago`, `3 h ago`, `4 d ago`. */
export function formatRelativeTime(at: number, now: number): string {
  const seconds = Math.max(0, Math.round((now - at) / 1000))
  if (seconds < 60) return "just now"
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  return `${Math.floor(hours / 24)} d ago`
}
